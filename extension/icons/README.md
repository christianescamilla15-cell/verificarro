# Icons

Genera tres PNG con el logo de Verificarro y guardalos como:

- `icon16.png` — 16x16 (toolbar)
- `icon48.png` — 48x48 (extension management)
- `icon128.png` — 128x128 (Chrome Web Store y popup)

Mientras no existan, la extension carga pero el icono aparece como un
placeholder. Para desarrollo local funciona sin ellos.

Sugerencia rapida con ImageMagick:

```bash
convert frontend/public/logo.png -resize 16x16 extension/icons/icon16.png
convert frontend/public/logo.png -resize 48x48 extension/icons/icon48.png
convert frontend/public/logo.png -resize 128x128 extension/icons/icon128.png
```
