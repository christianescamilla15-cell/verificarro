#!/usr/bin/env python3
"""Confidencialidad (N12): falla si algún archivo versionado menciona un término vetado.

La lista NO vive en el repositorio (ni siquiera en huellas: un término corto se recupera por fuerza bruta).
En CI llega por el secreto CONFIDENCIAL_TERMINOS; en local, de ~/.config/confidencial/terminos.txt.
Una expresión regular por línea, sin distinguir mayúsculas. El reporte NUNCA imprime el término: sólo
archivo, línea y el número de la regla, porque los registros de un repo público son públicos.

Sale con 1 si encuentra algo, con 2 si no hay lista o no revisó ningún archivo (no se aprueba por no mirar).

`--solo-dependencias <base>` es el modo de los PR de Dependabot: GitHub no les pasa los secretos de Actions (y no
debe: el paquete nuevo corre durante la instalación). Sin lista no se puede buscar términos, así que se comprueba
lo que sí se puede: que el PR sólo toque manifiestos y candados de dependencias, versiones de acciones o imágenes.
Cualquier otro archivo hace fallar el check; el árbol completo se vuelve a medir con la lista al fusionar en main.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

LOCAL = Path.home() / '.config' / 'confidencial' / 'terminos.txt'


def reglas() -> list[re.Pattern]:
    texto = os.environ.get('CONFIDENCIAL_TERMINOS') or ''
    if not texto and LOCAL.exists():
        texto = LOCAL.read_text(encoding='utf-8')
    lineas = [linea.strip() for linea in texto.splitlines()]
    return [re.compile(linea, re.IGNORECASE) for linea in lineas if linea and not linea.startswith('#')]


def archivos() -> list[str]:
    salida = subprocess.run(['git', 'ls-files', '-z'], capture_output=True, check=True).stdout
    return [a for a in salida.decode().split('\0') if a]


# Lo único que un PR de dependencias puede tocar.
DEPENDENCIAS = re.compile(
    r'(^|/)(requirements[^/]*\.(txt|in)|constraints[^/]*\.txt|pyproject\.toml|poetry\.lock|uv\.lock|Pipfile(\.lock)?'
    r'|package\.json|package-lock\.json|npm-shrinkwrap\.json|pnpm-lock\.yaml|yarn\.lock'
    r'|Dockerfile[^/]*|docker-compose[^/]*\.ya?ml|go\.(mod|sum)|Cargo\.(toml|lock)|[^/]+\.csproj)$'
    r'|^\.github/workflows/[^/]+\.ya?ml$')


def solo_dependencias(base: str) -> int:
    salida = subprocess.run(['git', 'diff', '--name-only', f'{base}...HEAD'],
                            capture_output=True, check=True).stdout.decode()
    cambiados = [a for a in salida.splitlines() if a]
    fuera = [a for a in cambiados if not DEPENDENCIAS.search(a)]
    print(f'confidencialidad (PR de dependencias): {len(cambiados)} archivos cambiados contra {base} · '
          f'{len(fuera)} fuera de manifiestos/candados')
    if not cambiados:
        print('confidencialidad: el PR no cambia ningún archivo → no medible')
        return 2
    for a in fuera:
        print('   no es de dependencias:', a)
    return 1 if fuera else 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == '--solo-dependencias':
        return solo_dependencias(sys.argv[2])
    rs = reglas()
    if not rs:
        print('confidencialidad: SIN LISTA de términos '
              '(secreto CONFIDENCIAL_TERMINOS o ~/.config/confidencial/terminos.txt) → no medible')
        return 2
    hallazgos, revisados = [], 0
    for ruta in archivos():
        p = Path(ruta)
        try:
            datos = p.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            continue
        if b'\0' in datos[:8192]:          # binario
            continue
        revisados += 1
        for n, linea in enumerate(datos.decode('utf-8', 'replace').splitlines(), 1):
            for k, r in enumerate(rs, 1):
                if r.search(linea):
                    hallazgos.append(f'{ruta}:{n} · regla #{k}')
    print(f'confidencialidad: {revisados} archivos revisados con {len(rs)} reglas · '
          f'{len(hallazgos)} hallazgos')
    if revisados == 0:
        print('confidencialidad: no se revisó ningún archivo → no medible')
        return 2
    for h in hallazgos[:200]:
        print('  ', h)
    return 1 if hallazgos else 0


if __name__ == '__main__':
    sys.exit(main())
