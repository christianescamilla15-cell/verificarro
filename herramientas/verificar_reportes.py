#!/usr/bin/env python3
"""Un check que terminó no es un check que analizó (lección de producción: escaneos «verdes» que sólo
subían el paquete). Este script falla si el reporte de una herramienta no prueba que miró algo.

    python3 herramientas/verificar_reportes.py semgrep semgrep.json
    python3 herramientas/verificar_reportes.py trivy trivy.json
    python3 herramientas/verificar_reportes.py sbom sbom.spdx.json
    python3 herramientas/verificar_reportes.py pytest reporte.xml
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def semgrep(d: dict) -> tuple[int, str]:
    n = len(d.get('paths', {}).get('scanned', []))
    return n, f'{n} archivos escaneados'


def trivy(d: dict) -> tuple[int, str]:
    resultados = d.get('Results') or []
    paquetes = sum(len(r.get('Packages') or []) for r in resultados)
    return len(resultados), f'{len(resultados)} manifiestos, {paquetes} paquetes inventariados'


def sbom(d: dict) -> tuple[int, str]:
    n = len(d.get('packages') or [])
    return n, f'{n} componentes en el SBOM'


def pytest(ruta: Path) -> tuple[int, str]:
    raiz = ET.parse(ruta).getroot()
    suites = [raiz] if raiz.tag == 'testsuite' else raiz.findall('testsuite')
    n = sum(int(s.get('tests', 0)) for s in suites)
    return n, f'{n} pruebas ejecutadas'


def main() -> int:
    tipo, archivo = sys.argv[1], Path(sys.argv[2])
    if not archivo.exists() or archivo.stat().st_size == 0:
        print(f'{tipo}: el reporte {archivo} no existe o está vacío → el análisis no ocurrió')
        return 1
    if tipo == 'pytest':
        n, texto = pytest(archivo)
    else:
        d = json.loads(archivo.read_text(encoding='utf-8'))
        n, texto = {'semgrep': semgrep, 'trivy': trivy, 'sbom': sbom}[tipo](d)
    print(f'{tipo}: {texto}')
    if n <= 0:
        print(f'{tipo}: no analizó nada → falla (un check vacío no es un check verde)')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
