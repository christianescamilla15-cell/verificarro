import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app import __version__
from app.api import analyze, auth, health, payments, scan
from app.config import get_settings
from app.rate_limit import limiter

logger = logging.getLogger(__name__)


def _init_sentry() -> None:
    """Init Sentry SDK ANTES de crear FastAPI (MOD-010).

    Sentry recomienda que sentry_sdk.init() corra antes de instanciar
    la app porque la integración FastAPI auto-detecta y wrappea las
    routes en su loader. Si init corre después, algunos middleware se
    quedan sin instrumentar.

    No-op si `SENTRY_DSN` está vacío (modo dev sin telemetría).
    """
    settings = get_settings()
    dsn = settings.sentry_dsn.strip()
    if not dsn:
        logger.info("Sentry deshabilitado (SENTRY_DSN vacío)")
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        # Sample rate de performance traces. 0.1 = 10% para no llenar
        # el free tier (5K events/mes). Cuando crezcamos a paid, subir
        # a 1.0 para identificar slow endpoints.
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # NO mandamos PII a Sentry (LFPDPPP MX). Email, IP, body de
        # requests con datos personales NO van. Sentry sigue capturando
        # stack traces, paths, status codes — todo lo que necesitamos
        # para debug sin violar privacy.
        send_default_pii=False,
        # Tag por environment (production / development) — útil para
        # filtrar en el dashboard de Sentry.
        environment=settings.env,
        release=f"verificarro@{__version__}",
        # Deshabilita el captureo automático de logs INFO/WARNING como
        # eventos. Solo errors/exceptions. Ahorra cuota.
        attach_stacktrace=False,
        # `before_send` filtra eventos antes de mandarlos. Útil para
        # ignorar excepciones esperadas (rate limits, 4xx) que NO son
        # bugs reales. Solo queremos saber de los 5xx y crashes.
        before_send=_sentry_before_send,
    )
    logger.info("Sentry inicializado (env=%s)", settings.env)


def _sentry_before_send(event, hint):
    """Filtra eventos antes de mandarlos a Sentry.

    Devuelve `None` para descartar el evento. Devuelve el evento para
    enviarlo. Útil para no llenar la cuota free con ruido esperado.
    """
    # Si la excepción es una HTTPException con status <500, NO la
    # mandamos — son errores de cliente esperados, no bugs.
    exc_info = hint.get("exc_info") if hint else None
    if exc_info:
        from fastapi import HTTPException
        from slowapi.errors import RateLimitExceeded as _RLE
        exc = exc_info[1]
        if isinstance(exc, HTTPException) and exc.status_code < 500:
            return None
        if isinstance(exc, _RLE):
            return None
    return event


# Sentry init ANTES de cualquier app code (incluyendo router imports).
# Si esto falla, la app sigue arrancando — Sentry nunca debe bloquear
# el servicio.
try:
    _init_sentry()
except Exception:  # noqa: BLE001
    logger.exception("Sentry init falló (no-bloqueante)")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # MOD-012: tras un restart de Render (deploy, OOM, idle wakeup), los
    # background tasks en curso se pierden. Si un Payment fue marcado PAID
    # pero el pipeline aún no había terminado, el reporte queda sin
    # generar. `recover_orphan_paid_payments` detecta esos huérfanos en
    # los últimos 30 min y los re-encola. Failure tolerant: si la query
    # falla (e.g. DB no disponible al boot), log y continue — el server
    # arranca igual, los webhooks futuros funcionarán.
    try:
        from app.services.report_generator import recover_orphan_paid_payments
        recovered = await recover_orphan_paid_payments()
        if recovered:
            logger.info(
                "Startup orphan recovery: %d payments re-encolados",
                len(recovered),
            )
    except Exception:  # noqa: BLE001
        logger.exception("Startup orphan recovery falló (no-bloqueante)")
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
