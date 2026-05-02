"""Email sender. SMTP en producción, stdout-stub en dev.

Si `SMTP_HOST` está vacío (default en dev), el envío imprime el
mensaje al stdout en lugar de mandarlo. Esto permite probar el flow
de magic link sin configurar SMTP — el "email" aparece en los logs
del backend y Christian copia/pega el link.

En producción configurar SendGrid (`smtp.sendgrid.net:587`), Resend
(`smtp.resend.com:465`), Postmark (`smtp.postmarkapp.com:587`) o el
SMTP del hosting de email.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger(__name__)


def mask_email(email: str | None) -> str:
    """Enmascara un email para logs (LFPDPPP / H-2).

    `christian@gmail.com` → `chr***@gmail.com`
    `a@b.mx` → `a***@b.mx`  (1-char local stays as-is)
    `None` / `""` → `<empty>`
    `no-at-sign` → `***`

    El log retention de Render + búsqueda searchable convierten emails
    en datos personales recuperables. Esta máscara conserva enough
    info para troubleshooting (qué dominio, prefix recognizable) sin
    exponer la dirección completa.
    """
    if not email:
        return "<empty>"
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        return f"{local}***@{domain}"
    return f"{local[:3]}***@{domain}"


async def send_magic_link_email(to_email: str, magic_link_url: str) -> None:
    """Manda el email con el magic link. En dev (sin SMTP_HOST) imprime."""
    settings = get_settings()

    subject = "Tu link para entrar a Verificarro"
    html_body = _render_magic_link_html(magic_link_url, settings.magic_link_ttl_minutes)
    text_body = _render_magic_link_text(magic_link_url, settings.magic_link_ttl_minutes)

    if not settings.smtp_host:
        # Dev mode — stub al stdout
        print(
            "\n" + "=" * 70 + "\n"
            f"📧 [DEV] Email a {to_email}\n"
            f"   Asunto: {subject}\n"
            f"   Link: {magic_link_url}\n"
            f"   (En prod esto sería un email vía SMTP)\n"
            + "=" * 70 + "\n",
            flush=True,
        )
        logger.info(
            "Magic link generated for %s (SMTP not configured)",
            mask_email(to_email),
        )
        return

    # Producción — SMTP real
    msg = EmailMessage()
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    def _send_sync() -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

    try:
        await asyncio.to_thread(_send_sync)
        logger.info("Magic link sent to %s", mask_email(to_email))
    except (smtplib.SMTPException, OSError) as exc:
        # SMTPException cubre: auth fail, recipient refused, server disconnect.
        # OSError cubre: DNS resolución, timeout, connection refused.
        logger.exception("SMTP send failed for %s", mask_email(to_email))
        raise RuntimeError(f"No pude enviar el email: {exc}") from exc


# ---------------------------------------------------------------------------
# Templates


def _render_magic_link_html(link: str, ttl_min: int) -> str:
    return f"""\
<!DOCTYPE html>
<html lang="es-MX">
<body style="font-family: system-ui, sans-serif; max-width: 540px; margin: 40px auto; padding: 0 20px; color: #11161c;">
  <h1 style="background: linear-gradient(90deg, #ffb84d, #ff6b6b); -webkit-background-clip: text; background-clip: text; color: transparent; font-size: 32px; margin-bottom: 8px;">Verificarro</h1>
  <p style="font-size: 16px; line-height: 1.6;">Hola, hiciste login en Verificarro. Da clic en este botón para entrar:</p>
  <p style="margin: 24px 0;">
    <a href="{link}" style="display: inline-block; background: #ffb84d; color: #1a1300; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 600;">Entrar a Verificarro</a>
  </p>
  <p style="color: #6b7280; font-size: 14px;">Este link funciona por {ttl_min} minutos. Si no fuiste tú, ignora este email — no se puede usar más de una vez.</p>
  <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">
  <p style="color: #9ca3af; font-size: 12px;">¿No funciona el botón? Copia y pega este URL:<br><span style="word-break: break-all;">{link}</span></p>
</body>
</html>
"""


def _render_magic_link_text(link: str, ttl_min: int) -> str:
    return (
        f"Hola, hiciste login en Verificarro.\n\n"
        f"Da clic en este link para entrar:\n{link}\n\n"
        f"Funciona por {ttl_min} minutos. Si no fuiste tú, ignora este email."
    )


# ---------------------------------------------------------------------------
# Reporte (con PDF adjunto)


async def send_report_email(
    to_email: str,
    pdf_bytes: bytes,
    *,
    title_hint: str = "tu reporte",
    score: int | None = None,
    risk_level: str | None = None,
    report_id: str | None = None,
    report_url: str | None = None,
) -> None:
    """Manda al usuario su reporte completo por email con el PDF adjunto.

    Llamado desde `unlock_report_for_payment` cuando el pago se confirma
    y el reporte está listo. El email incluye:
    - Subject con score si está disponible
    - HTML body con score chip + link a la versión web
    - PDF adjunto (~7-10KB, listo para imprimir o archivar)

    Failure tolerant: si SMTP falla o no está configurado, loguea y
    sigue (el usuario sigue teniendo el reporte en la web — el email
    es bonus, no requirement).
    """
    settings = get_settings()

    score_part = f" — {score}/100" if score is not None else ""
    subject = f"Tu reporte Verificarro{score_part}: {title_hint}"

    html_body = _render_report_html(
        title_hint=title_hint, score=score, risk_level=risk_level,
        report_url=report_url,
    )
    text_body = _render_report_text(
        title_hint=title_hint, score=score, report_url=report_url,
    )

    if not settings.smtp_host:
        # Dev mode — stub stdout
        print(
            "\n" + "=" * 70 + "\n"
            f"📧 [DEV] Reporte email a {to_email}\n"
            f"   Asunto: {subject}\n"
            f"   PDF adjunto: {len(pdf_bytes)} bytes\n"
            f"   URL: {report_url or '(no provista)'}\n"
            + "=" * 70 + "\n",
            flush=True,
        )
        logger.info(
            "Report email stubbed for %s (SMTP not configured, %d bytes PDF)",
            mask_email(to_email), len(pdf_bytes),
        )
        return

    msg = EmailMessage()
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    pdf_filename = f"verificarro-{report_id[:8] if report_id else 'reporte'}.pdf"
    msg.add_attachment(
        pdf_bytes,
        maintype="application", subtype="pdf",
        filename=pdf_filename,
    )

    def _send_sync() -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

    try:
        await asyncio.to_thread(_send_sync)
        logger.info(
            "Report email sent to %s (%d bytes PDF, report_id=%s)",
            mask_email(to_email), len(pdf_bytes), report_id,
        )
    except (smtplib.SMTPException, OSError) as exc:
        # No re-raise — email es bonus, no bloqueante para unlock.
        # Cubre auth/recipient/disconnect (SMTP) + network (OSError).
        logger.warning(
            "Report email failed for %s: %s", mask_email(to_email), exc,
        )


def _render_report_html(
    *, title_hint: str, score: int | None, risk_level: str | None,
    report_url: str | None,
) -> str:
    risk_color = {
        "green": "#16a34a", "yellow": "#d97706", "red": "#dc2626",
    }.get(risk_level or "", "#0084ff")
    risk_label = {
        "green": "RIESGO BAJO", "yellow": "PRECAUCIÓN", "red": "ALTO RIESGO",
    }.get(risk_level or "", "REPORTE LISTO")

    score_block = ""
    if score is not None:
        score_block = f"""
  <div style="text-align: center; margin: 32px 0; padding: 24px; border: 2px solid {risk_color}; border-radius: 12px; background: #f8fafc;">
    <div style="font-size: 56px; font-weight: 800; color: {risk_color}; line-height: 1;">{score}<span style="font-size: 24px; color: #94a3b8;">/100</span></div>
    <div style="font-size: 12px; font-weight: 700; color: {risk_color}; letter-spacing: 0.16em; margin-top: 8px;">{risk_label}</div>
  </div>
        """

    web_link = ""
    if report_url:
        web_link = f"""
  <p style="text-align: center; margin: 24px 0;">
    <a href="{report_url}" style="display: inline-block; background: #0084ff; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 600;">Ver reporte en la web</a>
  </p>
        """

    return f"""\
<!DOCTYPE html>
<html lang="es-MX">
<body style="font-family: system-ui, -apple-system, sans-serif; max-width: 580px; margin: 40px auto; padding: 0 20px; color: #0f172a;">
  <h1 style="color: #0084ff; font-size: 28px; margin-bottom: 8px;">Verificarro</h1>
  <p style="font-size: 16px; line-height: 1.6;">¡Listo! Tu reporte de <strong>{title_hint}</strong> ya está disponible.</p>
  {score_block}
  <p style="font-size: 15px; line-height: 1.6;">El reporte completo viene <strong>adjunto en PDF</strong> en este mismo email — guárdalo, imprímelo, compártelo con tu mecánico.</p>
  {web_link}
  <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 32px 0;">
  <p style="color: #475569; font-size: 13px; line-height: 1.5;">
    <strong>Recuerda:</strong> Verificarro detecta fraudes documentales y de fotos.
    Antes de cerrar trato, pídele al vendedor revisión mecánica con tu persona
    de confianza.
  </p>
  <p style="color: #94a3b8; font-size: 12px; margin-top: 24px;">
    Verificarro · Hecho en México · verificarro.mx
  </p>
</body>
</html>
"""


def _render_report_text(
    *, title_hint: str, score: int | None, report_url: str | None,
) -> str:
    score_part = f"\nScore: {score}/100\n" if score is not None else "\n"
    web_part = f"\nVer en la web: {report_url}\n" if report_url else ""
    return (
        f"¡Listo! Tu reporte de {title_hint} ya está disponible.\n"
        f"{score_part}"
        "El reporte completo viene adjunto en PDF en este mismo email.\n"
        f"{web_part}"
        "\n"
        "Verificarro · Hecho en México · verificarro.mx\n"
    )
