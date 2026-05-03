"""Stealth init script para Playwright Chromium.

Google reCaptcha (especialmente invisible v2 con threshold alto como
REPUVE) detecta automation comparando el browser fingerprint contra
el de un Chrome real. Headless Chromium tiene N pistas obvias:

- `navigator.webdriver === true`
- `navigator.plugins.length === 0`
- `navigator.languages` vacío
- `chrome` object ausente o incompleto
- WebGL renderer dice "SwiftShader" (renderer software de Chromium headless)
- Permission API permite preguntas que browsers reales no permiten
- Canvas fingerprint determinista (sin variaciones por GPU)
- userAgent contiene "HeadlessChrome"

Este módulo aplica los parches conocidos como "stealth" — patrón
probado por años en `puppeteer-extra-plugin-stealth` y forks. No
garantiza pasar Google 100% pero sube la base de éxito ~25-35%.

## Trade-off

Estos parches NO son persistentes — se aplican vía init script en
cada page nueva. Performance: ~50ms extra al arrancar la página.
Detectabilidad por advanced anti-bot: aún detectable si Google
hace análisis profundo (audio fingerprint, click timing analysis,
etc.) pero sube significativamente la barrera.
"""

from __future__ import annotations

# Init script aplicado en cada page nueva. Combina técnicas estándar de
# stealth — referencias en cada sección.
_STEALTH_SCRIPT = r"""
// === navigator.webdriver: el flag más obvio ===
// IMPORTANTE: Chrome real devuelve `false`, NO `undefined`. El bot
// detector de rebrowser explícitamente flagga `=== undefined` como
// "you have it deleted manually" — eso es señal bot. Chrome stable
// retorna boolean false. Diagnóstico real:
//   typeof navigator.webdriver = "boolean", value = false  (real Chrome)
//   typeof navigator.webdriver = "undefined"                (mi bug)
Object.defineProperty(navigator, 'webdriver', {
    get: () => false,
    configurable: true,
});

// === Chrome runtime object ===
// Chromium headless no tiene `window.chrome` poblado. Real Chrome sí.
if (!window.chrome) {
    window.chrome = {
        runtime: {},
        loadTimes: function () {},
        csi: function () {},
        app: {},
    };
}

// === Permissions API ===
// Real Chrome rechaza ciertas queries; headless las acepta — eso lo delata.
const originalQuery = window.navigator.permissions
    ? window.navigator.permissions.query
    : null;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
}

// === Plugins array ===
// Chrome real reporta un array no-vacío (PDF Viewer, etc.)
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
        ];
        // Aproximamos la API de PluginArray
        plugins.item = (i) => plugins[i];
        plugins.namedItem = (n) => plugins.find(p => p.name === n);
        plugins.refresh = () => {};
        return plugins;
    },
    configurable: true,
});

// === Languages ===
Object.defineProperty(navigator, 'languages', {
    get: () => ['es-MX', 'es', 'en-US', 'en'],
    configurable: true,
});

// === WebGL renderer ===
// Headless reporta "SwiftShader" / "Mesa" — Chrome real reporta GPUs
// concretas tipo "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620, OpenGL 4.6)".
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function (parameter) {
    // UNMASKED_VENDOR_WEBGL = 37445
    if (parameter === 37445) return 'Intel Inc.';
    // UNMASKED_RENDERER_WEBGL = 37446
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.apply(this, arguments);
};

// Mismo patch para WebGL2
if (window.WebGL2RenderingContext) {
    const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function (parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter2.apply(this, arguments);
    };
}

// === navigator.deviceMemory & hardwareConcurrency ===
// Chrome real reporta valores plausibles; headless puede dar 0 o no-set.
if (!navigator.deviceMemory) {
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8,
        configurable: true,
    });
}
if (!navigator.hardwareConcurrency || navigator.hardwareConcurrency === 0) {
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
        configurable: true,
    });
}

// === Iframe.contentWindow.chrome ===
// Bug famoso de Chromium headless: iframes anidados no propagan window.chrome
try {
    const desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
    if (desc) {
        Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
            get: function () {
                const win = desc.get.apply(this);
                if (win && !win.chrome) {
                    win.chrome = window.chrome;
                }
                return win;
            },
        });
    }
} catch (e) {}

// === window.outerWidth / outerHeight ===
// En headless suelen ser 0; en Chrome real coinciden con innerWidth/Height.
Object.defineProperty(window, 'outerWidth', {
    get: () => window.innerWidth,
    configurable: true,
});
Object.defineProperty(window, 'outerHeight', {
    get: () => window.innerHeight,
    configurable: true,
});

// === Audio context fingerprint ===
// Google evalúa el "audio fingerprint" comparando el resultado de
// OfflineAudioContext.startRendering() — en GPU+OS reales hay variaciones
// micro de punto flotante; en headless es determinista (mismo hash siempre)
// lo que delata bot. Patch: inyectamos ruido imperceptible para que cada
// session tenga su huella única pero plausible.
try {
    const OfflineAudioCtx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (OfflineAudioCtx) {
        const origStart = OfflineAudioCtx.prototype.startRendering;
        OfflineAudioCtx.prototype.startRendering = function () {
            return origStart.apply(this, arguments).then(buf => {
                try {
                    for (let ch = 0; ch < buf.numberOfChannels; ch++) {
                        const data = buf.getChannelData(ch);
                        for (let i = 0; i < data.length; i++) {
                            // Noise floor ~1e-7: imperceptible auditivamente
                            // pero rompe el hash determinista
                            data[i] = data[i] + (Math.random() - 0.5) * 1e-7;
                        }
                    }
                } catch (e) {}
                return buf;
            });
        };
    }
} catch (e) {}

// === Canvas fingerprint ===
// Mismo principio: Google compara el hash del rendered canvas. Headless
// produce un hash determinista (mismo browser → mismo pixel-by-pixel).
// Patch: noise sutil al pixel data para variar el hash sin alterar
// visualmente el contenido.
try {
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function (...args) {
        const ctx = this.getContext('2d');
        if (ctx) {
            try {
                const w = this.width;
                const h = this.height;
                if (w > 0 && h > 0 && w * h < 2_000_000) {  // skip canvases enormes
                    const imgData = ctx.getImageData(0, 0, w, h);
                    // Pequeña perturbación en 1 de cada 50 píxeles
                    for (let i = 0; i < imgData.data.length; i += 200) {
                        imgData.data[i] = imgData.data[i] ^ 1;  // flip LSB
                    }
                    ctx.putImageData(imgData, 0, 0);
                }
            } catch (e) {}
        }
        return origToDataURL.apply(this, args);
    };
} catch (e) {}

// === Battery API ===
// Real Chrome expone navigator.getBattery() que devuelve un objeto con
// nivel/cargando. Headless puede no implementarlo o dar default. Faking
// uno con valores plausibles humanos (laptop a 75% no cargando):
try {
    if (!navigator.getBattery) {
        navigator.getBattery = function () {
            return Promise.resolve({
                charging: false,
                chargingTime: Infinity,
                dischargingTime: 14400,  // 4 horas — laptop normal
                level: 0.78,
                addEventListener: () => {},
                removeEventListener: () => {},
                onchargingchange: null,
                onchargingtimechange: null,
                ondischargingtimechange: null,
                onlevelchange: null,
            });
        };
    }
} catch (e) {}

// === MediaDevices enumerateDevices ===
// Headless reporta lista vacía; real Chrome reporta cámara/mic etc.
try {
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
        const origEnum = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
        navigator.mediaDevices.enumerateDevices = function () {
            return origEnum().then(devices => {
                if (devices.length > 0) return devices;
                // Inventar 2-3 devices típicos
                return [
                    { deviceId: 'default', kind: 'audioinput', label: '', groupId: 'g1' },
                    { deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'g1' },
                    { deviceId: 'cam0', kind: 'videoinput', label: '', groupId: 'g2' },
                ];
            });
        };
    }
} catch (e) {}

// === navigator.userAgentData (Step 3 fix) ===
// Bot detector flagga "Google Chrome is not presented in
// navigator.userAgentData. You might be using Google Chrome for Testing".
// Real Chrome stable expone 3 brands (Chromium + Not?A_Brand + Google Chrome).
// Headless/Testing solo expone 2. Spoof para que mostremos las 3.
try {
    if (navigator.userAgentData) {
        const origGetHighEntropyValues = navigator.userAgentData.getHighEntropyValues
            ? navigator.userAgentData.getHighEntropyValues.bind(navigator.userAgentData)
            : null;
        const fakeBrands = [
            { brand: 'Chromium', version: '130' },
            { brand: 'Not?A_Brand', version: '99' },
            { brand: 'Google Chrome', version: '130' },
        ];
        Object.defineProperty(navigator.userAgentData, 'brands', {
            get: () => fakeBrands,
            configurable: true,
        });
        // Patch fullVersionList también
        if (origGetHighEntropyValues) {
            navigator.userAgentData.getHighEntropyValues = function (hints) {
                return origGetHighEntropyValues(hints).then(data => {
                    if (data && Array.isArray(data.fullVersionList)) {
                        data.fullVersionList = [
                            { brand: 'Chromium', version: '130.0.6723.31' },
                            { brand: 'Not?A_Brand', version: '99.0.0.0' },
                            { brand: 'Google Chrome', version: '130.0.6723.31' },
                        ];
                    }
                    if (data && data.brands) data.brands = fakeBrands;
                    return data;
                });
            };
        }
    }
} catch (e) {}
"""


async def apply_stealth(page) -> None:
    """Aplica el init script de stealth en una page de Playwright.

    Llamar UNA VEZ después de `context.new_page()` y ANTES de `page.goto`.
    El init script se inyecta en cada document load (incluye iframes
    same-origin), por lo que sobrevive navigations.
    """
    await page.add_init_script(_STEALTH_SCRIPT)
