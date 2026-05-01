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
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
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
"""


async def apply_stealth(page) -> None:
    """Aplica el init script de stealth en una page de Playwright.

    Llamar UNA VEZ después de `context.new_page()` y ANTES de `page.goto`.
    El init script se inyecta en cada document load (incluye iframes
    same-origin), por lo que sobrevive navigations.
    """
    await page.add_init_script(_STEALTH_SCRIPT)
