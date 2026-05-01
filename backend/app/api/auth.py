"""Auth endpoints: magic link request + verify + me + logout.

Auth opcional para todo el resto de la API. El usuario puede comprar
reportes anónimos (sin cuenta); si está logueado, los reportes se
asocian a su user_id para historial.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.db.models import User
from app.db.session import SessionDep
from app.services.auth import (
    build_magic_link_url,
    create_session_token,
    decode_session_token,
    generate_magic_link,
    verify_magic_link,
)
from app.services.email import send_magic_link_email

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
async def request_link(
    body: RequestLinkBody, session: SessionDep
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
async def verify(body: VerifyBody, session: SessionDep) -> VerifyResponse:
    """Valida el magic link, marca último login y emite JWT de sesión."""
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

    # Magic link válido — invalidar (uso único) + actualizar last_login
    user.magic_link_hash = None
    user.magic_link_expires_at = None
    user.last_login_at = datetime.now(UTC)

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
