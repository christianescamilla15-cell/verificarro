from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app import __version__
from app.api import analyze, auth, health, payments, scan
from app.config import get_settings
from app.rate_limit import limiter


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


def _rate_limit_handler(request, exc):  # noqa: ARG001
    """Custom handler para 429 — devuelve mensaje en español MX."""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Demasiadas requests. Espera un momento e intenta otra vez.",
            "retry_after_seconds": getattr(exc, "retry_after", 60),
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Verificarro API",
        description="Verificador de auto usado para Marketplace MX",
        version=__version__,
        lifespan=lifespan,
    )

    # Rate limiter (slowapi) — instala antes de los routers para que
    # los decorators @limiter.limit(...) en endpoints surtan efecto.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(analyze.router, prefix="/api")
    app.include_router(payments.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(scan.router, prefix="/api")

    return app


app = create_app()
