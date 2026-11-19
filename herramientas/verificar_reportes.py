#!/usr/bin/env python3
"""Un check que terminó no es un check que analizó (lección de producción: escaneos «verdes» que sólo
subían el paquete). Este script falla si el reporte de una herramienta no prueba que miró algo.

    python3 herramientas/verificar_reportes.py semgrep semgrep.json
    python3 herramientas/verificar_reportes.py trivy trivy.json
    python3 herramientas/verificar_reportes.py sbom sbom.spdx.json
    python3 herramientas/verificar_reportes.py pytest reporte.xml
    python3 herramientas/verificar_reportes.py depurar-sarif semgrep.sarif   # quita lo suprimido en el código
"""
from __future__ import annotations

import json
import re
import sys
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
    # Sin parser de XML (evita la clase entera de ataques XXE/expansión): basta leer los atributos tests="N"
    # de cada <testsuite> del JUnit que genera pytest; <testsuites> no coincide por el límite de palabra.
    texto = ruta.read_text(encoding='utf-8', errors='replace')
    n = sum(int(x) for x in re.findall(r'<testsuite\b[^>]*?\btests="(\d+)"', texto))
    return n, f'{n} pruebas ejecutadas'


def depurar_sarif(ruta: Path) -> int:
    """Quita del SARIF los hallazgos suprimidos en el código (`nosemgrep` con su motivo): Semgrep los incluye
    marcados como suprimidos y la vista de seguridad de GitHub los contaría como alertas abiertas."""
    d = json.loads(ruta.read_text(encoding='utf-8'))
    total = quitados = 0
    for corrida in d.get('runs', []):
        resultados = corrida.get('results', [])
        total += len(resultados)
        vivos = [r for r in resultados if not r.get('suppressions')]
        quitados += len(resultados) - len(vivos)
        corrida['results'] = vivos
    ruta.write_text(json.dumps(d), encoding='utf-8')
    print(f'sarif: {total} hallazgos, {quitados} suprimidos en el código con su motivo, '
          f'{total - quitados} se suben')
    return 0


def main() -> int:
    tipo, archivo = sys.argv[1], Path(sys.argv[2])
    if tipo == 'depurar-sarif':
        return depurar_sarif(archivo)
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
