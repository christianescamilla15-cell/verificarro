// Inyectado en https://www2.repuve.gob.mx/ciudadania/*
//
// Si la URL trae el hash `vfr_scan=1`, asumimos que la extension orquesto
// la apertura de esta pestana — auto-rellenamos placa o NIV, hacemos click
// en "Buscar", esperamos el modal y mandamos el HTML al service worker.
//
// Si NO hay vfr_scan en el hash, no tocamos nada — el user esta navegando
// REPUVE manualmente y no queremos interferir.

(async function main() {
  const params = parseHash();
  if (!params.get("vfr_scan")) return;

  const requestId = params.get("vfr_request") || "";
  const plate = params.get("vfr_plate") || "";
  const vin = params.get("vfr_vin") || "";

  // Limpiar el hash para que un reload no re-dispare el flow
  try {
    history.replaceState(null, "", window.location.pathname + window.location.search);
  } catch (_) {
    // ignore
  }

  const plateInput = await waitForSelector(
    "input[placeholder*='placa' i]",
    15_000,
  );
  if (!plateInput) {
    sendResultToBackground(requestId, "", plate, vin, "input no encontrado");
    return;
  }

  if (plate) {
    setAngularInputValue(plateInput, plate);
  } else if (vin) {
    const vinInput = document.querySelector(
      "input[placeholder*='serie' i]",
    );
    if (vinInput) setAngularInputValue(vinInput, vin);
  }

  await sleep(800);

  // Si reCaptcha v2 visible esta presente, el user tendra que resolverlo.
  // Por ahora simplemente esperamos a que el modal aparezca — si nunca
  // llega es porque el captcha quedo sin resolver.
  // TODO Fase 2: detectar widget visible y mostrar nudge en el page.

  const submitBtn = findButtonByText(["Buscar", "Consultar"]);
  if (submitBtn) submitBtn.click();

  const modalHtml = await waitForModal(45_000);
  sendResultToBackground(requestId, modalHtml, plate, vin, modalHtml ? null : "modal timeout");
})();

function parseHash() {
  return new URLSearchParams(window.location.hash.replace(/^#/, ""));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForSelector(selector, timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const el = document.querySelector(selector);
    if (el) return el;
    await sleep(200);
  }
  return null;
}

function setAngularInputValue(input, value) {
  // Angular y React rastrean cambios via el setter nativo. Setear
  // input.value = "..." NO dispara los listeners. Hay que invocar el
  // setter del prototipo y emitir input + change manualmente.
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  ).set;
  setter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function findButtonByText(texts) {
  const lowered = texts.map((t) => t.toLowerCase());
  for (const btn of document.querySelectorAll("button")) {
    const t = (btn.innerText || "").trim().toLowerCase();
    if (t && lowered.some((label) => t.includes(label))) return btn;
  }
  return null;
}

async function waitForModal(timeoutMs) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const modal = document.querySelector(
      ".modal.in .modal-body, .modal.show .modal-body",
    );
    if (modal && modal.innerHTML.trim()) return modal.innerHTML;
    await sleep(300);
  }
  return "";
}

function sendResultToBackground(requestId, html, plate, vin, error) {
  try {
    chrome.runtime.sendMessage({
      type: "REPUVE_HTML",
      requestId,
      html,
      plate,
      vin,
      error: error || null,
    });
  } catch (_) {
    // service worker puede haberse dormido — no hay mucho que hacer aqui
  }
}
