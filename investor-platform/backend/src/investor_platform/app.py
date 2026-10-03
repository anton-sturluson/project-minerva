"""Loopback-only investor workspace API."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .accounts import router
from .db import make_engine, require_local_mode
from .hit_rate import router as hit_rate_router
from .ledger import router as ledger_router
from .performance import router as performance_router
from .trades import router as trades_router

LOCAL_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})


@asynccontextmanager
async def lifespan(app):
    require_local_mode()
    if not hasattr(app.state, "engine"):
        app.state.engine = make_engine()
    yield
    app.state.engine.dispose()


app = FastAPI(title="Minerva Investor Platform", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.include_router(ledger_router)
app.include_router(trades_router)
app.include_router(performance_router)
app.include_router(hit_rate_router)


@app.exception_handler(SQLAlchemyError)
async def database_unavailable(request, exc):
    return JSONResponse(
        {"detail": "Records are unavailable. Check the database and migrations, then retry."},
        status_code=503,
    )


app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def local_origin_only(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin is not None and origin not in LOCAL_ORIGINS:
        return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


class Health(BaseModel):
    status: str = "ok"
    service: str = "investor-platform"


@app.get("/api/health", response_model=Health)
def health() -> Health:
    return Health()


def main() -> None:
    # Deliberately local-only; remote access requires an authenticated deployment.
    uvicorn.run("investor_platform.app:app", host="127.0.0.1", port=8010)
