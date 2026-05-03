// Service worker — orquesta scans de REPUVE iniciados desde el page de
// verificarro.mx.
//
// Flow:
//   1. content/verificarro_bridge.js recibe SCAN_REPUVE del page,
//      reenvia aqui via runtime.sendMessage.
//   2. Esta SW abre una tab nueva a repuve.gob.mx con un hash que el
//      content script de REPUVE detecta (vfr_scan=1).
//   3. content/repuve_filler.js rellena placa, hace click, captura el
//      HTML del modal, lo manda a esta SW via REPUVE_HTML.
//   4. Esta SW POSTea el HTML al backend Verificarro que lo parsea
//      reusando parse_response() — no duplicamos parser en la extension.
//   5. La SW responde al callback original con el RepuveResult parseado.
//
// Tabs REPUVE se abren en background (active=false) para no robar foco
// y se cierran al recibir el HTML o al timeout.

const PENDING = new Map();
const SCAN_TIMEOUT_MS = 60_000;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== "object") return false;

  if (message.type === "SCAN_REPUVE") {
    handleScanRequest(message.payload || {})
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true; // async response
  }

  if (message.type === "REPUVE_HTML") {
    const pending = PENDING.get(message.requestId);
    if (pending) {
      pending.resolve({
        html: message.html || "",
        plate: message.plate || "",
        vin: message.vin || "",
        contentScriptError: message.error || null,
      });
      PENDING.delete(message.requestId);
    }
    sendResponse({ ok: true });
    return false;
  }

  return false;
});

async function handleScanRequest({ plate, vin, token, apiBase }) {
  if (!plate && !vin) throw new Error("Falta placa o NIV");
  if (!apiBase) throw new Error("apiBase requerido");
  if (!/^https?:\/\//.test(apiBase)) throw new Error("apiBase invalido");

  const requestId = crypto.randomUUID();

  const repuveUrl = new URL("https://www2.repuve.gob.mx:8443/ciudadania/");
  // Hash params no se mandan al servidor — perfecto para meta-data nuestra.
  repuveUrl.hash = new URLSearchParams({
    vfr_scan: "1",
    vfr_request: requestId,
    vfr_plate: plate || "",
    vfr_vin: vin || "",
  }).toString();

  const htmlPromise = new Promise((resolve, reject) => {
    PENDING.set(requestId, { resolve });
    setTimeout(() => {
      if (PENDING.has(requestId)) {
        PENDING.delete(requestId);
        reject(new Error("REPUVE no respondio a tiempo"));
      }
    }, SCAN_TIMEOUT_MS);
  });

  const repuveTab = await chrome.tabs.create({
    url: repuveUrl.toString(),
    active: false,
  });

  let captured;
  try {
    captured = await htmlPromise;
  } finally {
    try {
      await chrome.tabs.remove(repuveTab.id);
    } catch (_) {
      // tab pudo haberse cerrado solo
    }
  }

  if (captured.contentScriptError) {
    throw new Error(`REPUVE: ${captured.contentScriptError}`);
  }
  if (!captured.html) {
    throw new Error("REPUVE devolvio modal vacio");
  }

  const apiResponse = await fetch(`${apiBase.replace(/\/$/, "")}/api/repuve/extension-result`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      plate: captured.plate || plate || null,
      vin: captured.vin || vin || null,
      html: captured.html,
      source: "extension/0.1.0",
    }),
  });

  if (!apiResponse.ok) {
    const detail = await apiResponse.text().catch(() => "");
    throw new Error(`Backend HTTP ${apiResponse.status}: ${detail.slice(0, 120)}`);
  }

  return apiResponse.json();
}
