# Verificarro Helper — Chrome extension

Manifest V3 que automatiza la consulta REPUVE desde el navegador del
usuario. Soluciona el bottleneck de IP datacenter del scraper backend
porque el request a `repuve.gob.mx` sale del Chrome real del usuario,
con su IP residencial mexicana, sus cookies de Google y su huella
biometrica autentica — el reCaptcha v3 nunca dispara challenge.

## Como funciona

1. Usuario abre `verificarro.mx` en su Chrome con la extension instalada.
2. Pide un reporte de placa.
3. El frontend detecta la extension via `window.postMessage` handshake.
4. Llama `chrome.runtime.sendMessage({ type: "SCAN_REPUVE", ... })`.
5. La service worker abre una pestana en background a
   `repuve.gob.mx/ciudadania/#vfr_scan=1&vfr_plate=ABC123&vfr_request=...`.
6. El content script `repuve_filler.js` detecta el hash, rellena el
   formulario, hace click en "Buscar", espera el modal de resultado.
7. Captura el HTML del modal y lo manda al service worker.
8. La service worker POSTea el HTML a
   `POST /api/repuve/extension-result` del backend Verificarro.
9. El backend reusa el parser existente (`app/scrapers/repuve.py
   parse_response`) y devuelve un `RepuveResult` JSON.
10. El frontend recibe el resultado normalizado y lo integra al reporte.

No duplicamos el parser en JS — el HTML viaja al backend.

## Estructura

```
extension/
  manifest.json                     MV3 manifest
  background/
    service_worker.js               orquesta tabs + POST al backend
  content/
    repuve_filler.js                inyectado en repuve.gob.mx
    verificarro_bridge.js           inyectado en verificarro.mx
  popup/
    popup.html  popup.css  popup.js panel mini de status
  icons/                            16/48/128 px (ver icons/README.md)
```

## Instalacion local (desarrollo)

1. Abre `chrome://extensions/` en Chrome / Edge.
2. Activa **Modo desarrollador** (toggle arriba a la derecha).
3. Click **Cargar extension sin empaquetar**.
4. Selecciona la carpeta `extension/`.
5. La extension aparece en la barra. Si los iconos faltan ver
   `icons/README.md`.

Para probar contra `localhost:5173`:

```bash
cd frontend
npm run dev
```

Luego abre `http://localhost:5173`. El bridge debe responder al
handshake en menos de 800ms.

## Permisos solicitados

- `storage` — para persistir preferencias del user en futuras versiones.
- `tabs` — para crear/cerrar la pestana invisible a REPUVE.
- `host_permissions` — solo dominios `repuve.gob.mx` y `verificarro.*`,
  ningun acceso a otras paginas.

No se piden permisos de `activeTab` global, lectura de cookies, ni
acceso a todos los sitios.

## Privacidad

La extension solo:

- Lee el HTML del modal de resultado de REPUVE (publico, no requiere login).
- Manda ese HTML + la placa que el user introdujo al backend de
  Verificarro autenticando con el JWT del user.

No envia cookies, historia, ni datos de otras pestanas.

## Limitaciones conocidas (v0.1.0)

- Iconos placeholder — generar antes de publicar.
- No detecta reCaptcha visible — si Google lo dispara el user tiene
  que verlo y resolverlo (Fase 2: nudge UI en el popup).
- Service worker MV3 puede dormirse entre requests — el flow se
  re-dispara correctamente porque el message hace wake-up.
- Solo Chrome / Edge / Brave. Firefox WebExtensions API es similar pero
  no identica — port pendiente si hay demanda.

## Publicacion en Chrome Web Store

Pendiente:

- $5 USD fee one-time de Google Developer.
- Iconos finales.
- Screenshot de uso real.
- Politica de privacidad publica (puede ser pagina en verificarro.mx/privacy-extension).
- Justificacion de cada permiso para revision de Google.
