// Bridge entre el page script de verificarro.mx y el service worker de la
// extension. Inyectado en cada carga de verificarro.mx / verificarro.vercel.app.
//
// El page script no puede ver chrome.* APIs — necesita un puente. La
// comunicacion va por window.postMessage usando dos source IDs:
//
//   page  -> extension : { source: "verificarro-page",      type: ..., requestId, payload }
//   ext   -> page      : { source: "verificarro-extension", type: ..., requestId, ...    }
//
// Origen verificado en cada listener para evitar leak de mensajes a
// otros frames del MV3.

const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const SAFE_ORIGINS = new Set([
  "https://verificarro.vercel.app",
  "https://verificarro.mx",
  "http://localhost:5173",
]);

function originAllowed(origin) {
  if (SAFE_ORIGINS.has(origin)) return true;
  // Subdominios *.verificarro.mx
  return /^https:\/\/[a-z0-9-]+\.verificarro\.mx$/.test(origin);
}

window.addEventListener("message", (event) => { // nosemgrep: javascript.browser.security.insufficient-postmessage-origin-validation.insufficient-postmessage-origin-validation -- origen validado abajo con originAllowed() y event.source
  if (event.source !== window) return;
  if (!originAllowed(event.origin)) return;
  const data = event.data;
  if (!data || data.source !== "verificarro-page") return;

  const { type, requestId, payload } = data;

  if (type === "PING") {
    window.postMessage(
      {
        source: "verificarro-extension",
        type: "PONG",
        requestId,
        version: EXTENSION_VERSION,
      },
      event.origin,
    );
    return;
  }

  if (type === "SCAN_REPUVE") {
    chrome.runtime.sendMessage(
      { type: "SCAN_REPUVE", payload },
      (response) => {
        const safe = response || {
          ok: false,
          error: chrome.runtime.lastError?.message || "no response",
        };
        window.postMessage(
          {
            source: "verificarro-extension",
            type: "SCAN_REPUVE_RESULT",
            requestId,
            response: safe,
          },
          event.origin,
        );
      },
    );
  }
});

// Auto-anuncio al cargar la pagina. El page script puede usarlo como
// fallback rapido en lugar de PING.
window.postMessage(
  {
    source: "verificarro-extension",
    type: "READY",
    version: EXTENSION_VERSION,
  },
  window.location.origin,
);
