"""Auth endpoints: magic link request + verify + me + logout.

Auth opcional para todo el resto de la API. El usuario puede comprar
reportes anónimos (sin cuenta); si está logueado, los reportes se
asocian a su user_id para historial.

Nota: NO usamos `from __future__ import annotations` aquí porque
slowapi wrappa los endpoints con `@limiter.limit(...)` y eso rompe
el forward-ref resolution de Pydantic v2 con FastAPI body params.
Los tipos se evalúan eagerly y los Pydantic models están definidos
en este mismo módulo.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import case, desc, func, select, update

from app.db.models import Payment, PaymentStatus, ReportRecord, User
from app.db.session import SessionDep
from app.rate_limit import limiter
from app.services.auth import (
    build_magic_link_url,
    create_session_token,
    decode_session_token,
    generate_magic_link,
    verify_magic_link,
)
from app.services.email import send_magic_link_email

# Reportes incluidos por mes en cada tier suscripcional. Hard-coded (no
# config) porque el cap es identidad del tier, no precio. Si en algún
# momento se vuelve tunable se promueve a settings.
_TIER_MONTHLY_CAP: dict[str, int] = {
    "search": 50,
    "dealer": 500,
}

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


def _ensure_aware(dt: datetime) -> datetime:
    """Normaliza datetime a UTC-aware. SQLite con `DateTime(timezone=True)`
    pierde el tzinfo al recuperar — asumimos UTC en ese caso (consistente
    con cómo se guardan vía `_utc_now()` en `db.base`)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Schemas


class RequestLinkBody(BaseModel):
    email: EmailStr


class RequestLinkResponse(BaseModel):
    ok: bool = True
    message: str


class VerifyBody(BaseModel):
    email: EmailStr
    token: str


class MeResponse(BaseModel):
    id: str
    email: EmailStr
    last_login_at: datetime | None = None


class VerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: MeResponse


# ---------------------------------------------------------------------------
# Dependencies (definidas antes de los endpoints que las usan)


async def get_optional_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    """Devuelve el `User` si el JWT es válido, None si no hay token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_session_token(token)
    if not user_id:
        return None
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    """Variante strict — error 401 si no hay user autenticado."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Necesitas iniciar sesión",
        )
    return user


# ---------------------------------------------------------------------------
# Endpoints


@router.post("/auth/request-link", response_model=RequestLinkResponse)
@limiter.limit("5/minute")
async def request_link(
    request: Request, body: RequestLinkBody, session: SessionDep
) -> RequestLinkResponse:
    """Genera un magic link y lo envía al email. Idempotente — un
    request nuevo invalida el anterior."""
    email = body.email.lower().strip()

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email)
        session.add(user)
        await session.flush()

    link = generate_magic_link()
    user.magic_link_hash = link["token_hash"]
    user.magic_link_expires_at = link["expires_at"]

    url = build_magic_link_url(link["token"], email)
    try:
        await send_magic_link_email(email, url)
    except RuntimeError as exc:
        logger.warning("Email send failed for %s: %s", email, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pude enviar el email. Intenta de nuevo.",
        ) from exc

    return RequestLinkResponse(
        message=(
            f"Te mandamos un link a {email}. Da clic dentro de los próximos "
            "minutos. Si no llega, revisa spam."
        )
    )


@router.post("/auth/verify", response_model=VerifyResponse)
@limiter.limit("10/minute")
async def verify(
    request: Request, body: VerifyBody, session: SessionDep
) -> VerifyResponse:
    """Valida el magic link, marca último login y emite JWT de sesión.

    ### Single-use atómico (MOD-002)

    El consume del token es vía `UPDATE ... WHERE magic_link_hash=:hash`
    con check de filas afectadas. Si dos requests llegan con el mismo
    token válido, solo uno encuentra la fila con ese hash en la tabla
    (la otra ve `NULL` ya seteado) y emite JWT; el otro recibe 401.
    Sin esto había una race: ambos pasan el check `verify_magic_link`
    y ambos setean `hash=None` → 2 JWTs emitidos.
    """
    email = body.email.lower().strip()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if (
        user is None
        or not user.magic_link_hash
        or not user.magic_link_expires_at
        or not verify_magic_link(body.token, user.magic_link_hash)
        or _ensure_aware(user.magic_link_expires_at) < datetime.now(UTC)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Link inválido o expirado. Pide uno nuevo.",
        )

    # Consume atómico. Si otro request ganó la carrera entre el SELECT
    # de arriba y este UPDATE, magic_link_hash ya es NULL y rowcount=0.
    now = datetime.now(UTC)
    expected_hash = user.magic_link_hash
    consume = await session.execute(
        update(User)
        .where(User.id == user.id, User.magic_link_hash == expected_hash)
        .values(magic_link_hash=None, magic_link_expires_at=None, last_login_at=now)
    )
    if consume.rowcount != 1:
        # Otro request ya consumió este token. Mismo error que token inválido.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Link inválido o expirado. Pide uno nuevo.",
        )

    # Refrescamos el ORM para que el response tenga last_login_at actualizado.
    await session.refresh(user)

    token = create_session_token(user.id)
    return VerifyResponse(
        access_token=token,
        user=MeResponse(
            id=user.id,
            email=user.email,
            last_login_at=user.last_login_at,
        ),
    )


@router.get("/auth/me", response_model=MeResponse)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> MeResponse:
    """Devuelve el user actual (basado en `Authorization: Bearer <jwt>`)."""
    return MeResponse(
        id=user.id,
        email=user.email,
        last_login_at=user.last_login_at,
    )


@router.post("/auth/logout", status_code=status.HTTP_200_OK)
async def logout(
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    """Logout — el cliente debe descartar el JWT. Como los JWT son
    stateless, no hay invalidación server-side en MVP. (En v2:
    blacklist con TTL == JWT exp para invalidación instant.)"""
    logger.info("User %s logged out", user.email)
    return {"message": "Sesión cerrada. Descarta el token del cliente."}


# ---------------------------------------------------------------------------
# /api/auth/me/dashboard


class DashboardSubscription(BaseModel):
    tier: str  # "search" | "dealer"
    active: bool
    expires_at: datetime | None
    monthly_used: int  # reportes generados en los últimos 30 días
    monthly_cap: int


class DashboardSummary(BaseModel):
    total_reports: int
    reports_this_month: int
    avg_score: float | None
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    spent_mxn: float


class DashboardReport(BaseModel):
    id: str
    created_at: datetime
    make: str | None
    model: str | None
    year: int | None
    plate: str | None
    vin: str | None
    score: int
    risk_level: str
    status: str  # "preview" | "unlocked"
    source_url: str | None


class DashboardResponse(BaseModel):
    summary: DashboardSummary
    subscription: DashboardSubscription | None
    reports: list[DashboardReport]


@router.get("/auth/me/dashboard", response_model=DashboardResponse)
async def me_dashboard(
    user: Annotated[User, Depends(get_current_user)],
    session: SessionDep,
    limit: int = 20,
) -> DashboardResponse:
    """Tablero del usuario: stats agregadas + suscripción activa + últimos
    reportes. Una sola llamada para que el dashboard frontend no haga
    fan-out de requests."""
    limit = max(1, min(limit, 100))
    now = datetime.now(UTC)
    month_ago = now - timedelta(days=30)

    # ---------- Reports (últimos N + agregados) -----------------------
    reports_q = await session.execute(
        select(ReportRecord)
        .where(ReportRecord.user_id == user.id)
        .order_by(desc(ReportRecord.created_at))
        .limit(limit)
    )
    recent_reports = list(reports_q.scalars().all())

    # case((cond, 1), else_=0) genera CASE WHEN ... THEN 1 ELSE 0, que
    # SQLite y Postgres entienden igual. Evita el cast booleano→int que
    # diverge entre dialectos.
    agg_q = await session.execute(
        select(
            func.count(ReportRecord.id),
            func.avg(ReportRecord.score),
            func.sum(case((ReportRecord.risk_level == "high", 1), else_=0)),
            func.sum(case((ReportRecord.risk_level == "medium", 1), else_=0)),
            func.sum(case((ReportRecord.risk_level == "low", 1), else_=0)),
        ).where(ReportRecord.user_id == user.id)
    )
    total, avg_score, high_n, mid_n, low_n = agg_q.one()

    month_q = await session.execute(
        select(func.count(ReportRecord.id)).where(
            ReportRecord.user_id == user.id,
            ReportRecord.created_at >= month_ago,
        )
    )
    reports_this_month = int(month_q.scalar() or 0)

    # ---------- Spend (suma de Payment.amount_mxn paid) ----------------
    spent_q = await session.execute(
        select(func.coalesce(func.sum(Payment.amount_mxn), 0.0)).where(
            Payment.user_id == user.id,
            Payment.status == PaymentStatus.PAID,
        )
    )
    spent_mxn = float(spent_q.scalar() or 0.0)

    # ---------- Subscription (último Payment paid con tier sub) --------
    sub_q = await session.execute(
        select(Payment)
        .where(
            Payment.user_id == user.id,
            Payment.status == PaymentStatus.PAID,
            Payment.tier.in_(_TIER_MONTHLY_CAP.keys()),
        )
        .order_by(desc(Payment.paid_at))
        .limit(1)
    )
    last_sub = sub_q.scalar_one_or_none()

    subscription: DashboardSubscription | None = None
    if last_sub and last_sub.paid_at:
        paid_at = last_sub.paid_at
        if paid_at.tzinfo is None:
            paid_at = paid_at.replace(tzinfo=UTC)
        expires_at = paid_at + timedelta(days=30)
        subscription = DashboardSubscription(
            tier=last_sub.tier,
            active=expires_at > now,
            expires_at=expires_at,
            monthly_used=reports_this_month,
            monthly_cap=_TIER_MONTHLY_CAP[last_sub.tier],
        )

    return DashboardResponse(
        summary=DashboardSummary(
            total_reports=int(total or 0),
            reports_this_month=reports_this_month,
            avg_score=float(avg_score) if avg_score is not None else None,
            high_risk_count=int(high_n or 0),
            medium_risk_count=int(mid_n or 0),
            low_risk_count=int(low_n or 0),
            spent_mxn=spent_mxn,
        ),
        subscription=subscription,
        reports=[
            DashboardReport(
                id=r.id,
                created_at=r.created_at,
                make=r.make,
                model=r.model,
                year=r.year,
                plate=r.plate,
                vin=r.vin,
                score=r.score,
                risk_level=r.risk_level,
                status=r.status.value,
                source_url=r.source_url,
            )
            for r in recent_reports
        ],
    )


