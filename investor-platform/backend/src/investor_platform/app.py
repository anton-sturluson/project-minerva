"""Loopback API, with optional identity-checked Tailscale Serve access."""

import os
import re
from contextlib import asynccontextmanager
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .accounts import router
from .corrections import router as corrections_router
from .db import make_engine
from .hit_rate import router as hit_rate_router
from .ledger import router as ledger_router
from .performance import router as performance_router
from .trades import router as trades_router
from .valuation import router as valuation_router

LOCAL_ORIGINS = frozenset({"http://127.0.0.1:5173", "http://localhost:5173"})
WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


@asynccontextmanager
async def lifespan(app):
    if not hasattr(app.state, "engine"):
        app.state.engine = make_engine()
    yield
    app.state.engine.dispose()


class Health(BaseModel):
    status: str = "ok"
    service: str = "investor-platform"


def create_app(*, web_dist: Path = WEB_DIST) -> FastAPI:
    mode = os.environ.get("INVESTOR_MODE", "local")
    if mode not in {"local", "tailscale"}:
        raise RuntimeError("Unknown INVESTOR_MODE; use local or tailscale")
    remote = mode == "tailscale"
    origin = os.environ.get("TAILSCALE_ORIGIN", "")
    login = os.environ.get("TAILSCALE_USER_LOGIN", "")
    if remote:
        # Pin the whole authority (including the dedicated port), not arbitrary ts.net hosts.
        if not re.fullmatch(r"https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net:8444", origin):
            raise RuntimeError("TAILSCALE_ORIGIN must be https://<machine>.<tailnet>.ts.net:8444")
        if not login or login.strip() != login or not login.isascii():
            raise RuntimeError("TAILSCALE_USER_LOGIN must name the allowed Tailscale user")
        if not (web_dist / "index.html").is_file():
            raise RuntimeError("Build the frontend first: cd investor-platform/web && pnpm build")
        hosts = [urlsplit(origin).hostname]
    else:
        hosts = ["127.0.0.1", "localhost"]

    app = FastAPI(title="Minerva Investor Platform", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    app.include_router(ledger_router)
    app.include_router(trades_router)
    app.include_router(corrections_router)
    app.include_router(performance_router)
    app.include_router(valuation_router)
    app.include_router(hit_rate_router)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.exception_handler(SQLAlchemyError)
    async def database_unavailable(request, exc):
        return JSONResponse(
            {"detail": "Records are unavailable. Check the database and migrations, then retry."},
            status_code=503,
        )

    @app.middleware("http")
    async def access_boundary(request: Request, call_next):
        def deny(detail, status=403):
            return JSONResponse({"detail": detail}, status, headers={"Cache-Control": "no-store"})

        if remote:
            try:
                loopback = (
                    request.client is not None and ip_address(request.client.host).is_loopback
                )
            except ValueError:
                loopback = False
            # Serve removes supplied identity headers. Only its loopback proxy is trusted;
            # main() disables Uvicorn's forwarded-header rewriting of the socket peer.
            if (
                not loopback
                or request.headers.get("host") != urlsplit(origin).netloc
                or request.headers.getlist("tailscale-user-login") != [login]
            ):
                return deny("Access requires the allowed Tailscale user")
        allowed_origins = {origin} if remote else LOCAL_ORIGINS
        supplied_origin = request.headers.get("origin")
        if supplied_origin is not None and supplied_origin not in allowed_origins:
            return deny("Origin is not allowed")
        if (
            remote
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and supplied_origin != origin
        ):
            return deny("Writes require the Tailscale app origin")
        request.state.authenticated = True
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health", response_model=Health)
    def health() -> Health:
        return Health()

    if remote:
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app


app = create_app()


def main() -> None:
    from dotenv import load_dotenv

    # Explicit working-directory configuration; shell variables retain precedence.
    load_dotenv(".env", override=False)
    remote = os.environ.get("INVESTOR_MODE", "local") == "tailscale"
    uvicorn.run(create_app(), host="127.0.0.1", port=8011 if remote else 8010, proxy_headers=False)
