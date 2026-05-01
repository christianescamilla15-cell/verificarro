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
        logger.info("Magic link generated for %s (SMTP not configured)", to_email)
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
        logger.info("Magic link sent to %s", to_email)
    except Exception as exc:
        logger.exception("SMTP send failed for %s", to_email)
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
