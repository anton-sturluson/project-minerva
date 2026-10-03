"""Minimal local API. Portfolio persistence is added in IP-002."""

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

LOCAL_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})
app = FastAPI(title="Minerva Investor Platform", version="0.1.0")
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
