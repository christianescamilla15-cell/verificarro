# Seguridad

## Reportar una vulnerabilidad

Escribe a **christianescamilla15@gmail.com** con el asunto «Seguridad: Verificarro». Respondo en 72 horas
hábiles y publico el arreglo con su aviso. Por favor no abras un issue público para vulnerabilidades.

## Qué revisa cada cambio

Flujos `.github/workflows/ci.yml` y `.github/workflows/seguridad.yml` (también cada lunes, para CVE nuevas):

| Revisión | Herramienta | Bloquea |
|---|---|---|
| Análisis estático | CodeQL (python, javascript-typescript) + Semgrep `p/default` | sí (Semgrep) |
| Dependencias, configuración e IaC (Dockerfiles) | Trivy | sí, en CRITICAL/HIGH con arreglo publicado |
| Secretos en toda la historia | gitleaks | sí |
| Datos de terceros | revisión de confidencialidad | sí |
| Inventario de componentes | SBOM (syft, SPDX) | no: se publica con cada versión |
| Reglas de negocio y de seguridad | pytest (`docs/reglas.md`, sección 7) | sí |

Cada revisión debe probar que analizó algo (archivos o paquetes > 0); un reporte vacío cuenta como fallo
(`herramientas/verificar_reportes.py`). Dependabot propone actualizaciones semanales de pip (`backend/`),
npm (`frontend/`), imágenes Docker y acciones de GitHub (ancladas por SHA).

## Controles en la aplicación

| Riesgo | Control | Dónde |
|---|---|---|
| Webhooks de pago falsificados | Firma HMAC de Mercado Pago con ventana anti-repetición; monto verificado antes de acreditar; máquina de estados que no deja «desacreditar» un pago | `app/api/payments.py`, `app/db/models/payment.py` |
| Arranque con secretos de ejemplo | En `ENV=production` la app no arranca sin `JWT_SECRET` fuerte, `FERNET_KEY` y `MP_WEBHOOK_SECRET` | `app/config.py` |
| Datos personales en la base | Placa, VIN y correo del pago cifrados con Fernet; se enmascaran en los logs | `app/services/crypto.py`, `app/db/types.py` |
| Acceso a reportes ajenos | Token de sondeo HMAC por pago; enlace mágico de un solo uso con vencimiento | `app/api/payments.py`, `app/api/auth.py` |
| Abuso de endpoints públicos | Límite por IP (slowapi) | `app/rate_limit.py` |
| SSRF al descargar fotos | Sólo http(s) a IPs públicas; bloquea privadas, loopback y metadatos de nube | `app/services/photo_fetcher.py` |
| Sidecar de REPUVE expuesto | Token Bearer compartido; sin token configurado responde 503 | `app/scraper_main.py` |
| Cabeceras del front | CSP, HSTS, `X-Frame-Options: DENY`, `nosniff` | `frontend/vercel.json` |

Los secretos viven sólo en las variables de entorno de Render y Vercel (`render.yaml` los declara con
`sync: false` o `generateValue`), nunca en el repo. `docker-compose.yml` trae una contraseña de Postgres
SÓLO para la base local de desarrollo.

## Excepciones y falsos positivos

Toda excepción queda versionada, con motivo, y se revisa; nunca se apaga una regla completa.

1. **Vulnerabilidad sin arreglo o no alcanzable** → una línea en `.trivyignore`:
   `CVE-AAAA-NNNNN exp:AAAA-MM-DD  # motivo`. La fecha de vencimiento es obligatoria (máximo 90 días);
   al vencer, Trivy la vuelve a reportar y bloquea. Hoy no hay ninguna.
2. **Falso positivo de Semgrep** → comentario en la línea con la regla exacta y el motivo:
   `# nosemgrep: <id-de-la-regla> -- motivo`. Hoy hay 9, revisados el 2026-11-19 (SQL armado con literales
   y valores parametrizados, un log que no imprime el token, un origen de `postMessage` validado en otra
   función, un `<link rel="canonical">`).
3. **Archivo excluido de un escáner** → sólo con comentario en el flujo. Hoy: ninguno (`verificar_reportes.py` ya no usa un parser de XML)
   en Semgrep (lee con `xml.etree` el junit que genera el mismo job).
4. Quien agrega la excepción la justifica en el PR; el dueño del repo (CODEOWNERS) la aprueba.
