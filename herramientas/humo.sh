#!/usr/bin/env bash
# Prueba de humo posterior a un despliegue (o a una reversa). Sale con 0 sólo si todo responde como debe.
#
#   herramientas/humo.sh <url-api> [url-front]
#   herramientas/humo.sh https://verificarro-api.onrender.com https://verificarro.mx
#
# Render Starter puede tardar en despertar: cada llamada espera hasta HUMO_TIMEOUT segundos (90 por omisión).
set -uo pipefail

API="${1:?uso: herramientas/humo.sh <url-api> [url-front]}"
FRONT="${2:-}"
TIMEOUT="${HUMO_TIMEOUT:-90}"
API="${API%/}"
FRONT="${FRONT%/}"
fallas=0

ok()    { echo "  ok    $1"; }
falla() { echo "  FALLA $1"; fallas=$((fallas + 1)); }

echo "humo: API ${API}"

salud="$(curl -fsS --max-time "$TIMEOUT" "${API}/health" 2>&1)"
if printf '%s' "$salud" | grep -q '"status":"ok"'; then
  version="$(printf '%s' "$salud" | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')"
  ok "/health status=ok version=${version:-?}"
else
  falla "/health: ${salud:0:200}"
fi

config="$(curl -fsS --max-time "$TIMEOUT" "${API}/api/config" 2>&1)"
if printf '%s' "$config" | grep -q '"basic_mxn"'; then
  ok "/api/config publica precios"
else
  falla "/api/config: ${config:0:200}"
fi

# Un endpoint protegido debe rechazar sin credenciales (prueba que la app real, no un proxy, contesta).
codigo="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "${API}/api/auth/me")"
if [ "$codigo" = "401" ]; then
  ok "/api/auth/me sin token → 401"
else
  falla "/api/auth/me sin token devolvió ${codigo} (se esperaba 401)"
fi

if [ -n "$FRONT" ]; then
  echo "humo: front ${FRONT}"
  html="$(curl -fsS --max-time "$TIMEOUT" "${FRONT}/" 2>&1)"
  if printf '%s' "$html" | grep -q 'id="root"'; then
    ok "/ sirve la SPA"
  else
    falla "/ no sirve la SPA: ${html:0:200}"
  fi
  # Las rutas del cliente deben reescribirse a index.html (vercel.json).
  codigo="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "${FRONT}/precios")"
  if [ "$codigo" = "200" ]; then
    ok "/precios (ruta de la SPA) → 200"
  else
    falla "/precios devolvió ${codigo}"
  fi
fi

if [ "$fallas" -gt 0 ]; then
  echo "humo: ${fallas} falla(s)"
  exit 1
fi
echo "humo: todo en orden"
