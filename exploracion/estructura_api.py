"""Estructura de los registros de la consulta de la tabla (sin valores personales).

En la sesión de exploración elige el periodo indicado (con la selección de personas
que ya tenga la pantalla), recorre las páginas y reporta:
- nombres de campos de los registros y tipo de cada uno,
- largo de las listas anidadas (p. ej. periodos de tiempo por registro),
- conteo de registros por fecha y suma de elementos anidados por fecha.
Solo imprime nombres de campos, fechas y números.

Uso: uv run --no-sync python exploracion/estructura_api.py "Mes actual"
"""

import json
import re
import sys
from collections import Counter
from typing import Any

from cdp import _pagina
from playwright.sync_api import sync_playwright

API_REGISTROS = "/ISAPI/Bumblebee/AttendancePlugin/V1/Record"
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}")


def fecha_de(registro: dict[str, Any]) -> str:
    """Primer campo cuyo valor parezca una fecha (solo se usa la parte AAAA-MM-DD)."""
    for v in registro.values():
        if isinstance(v, str) and FECHA.match(v):
            return v[:10]
    return "?"


def main(periodo: str) -> None:
    with sync_playwright() as p:
        page = _pagina(p)
        if page.locator("button.login-btn").filter(visible=True).count():
            sys.exit("La sesión de exploración expiró (se ve el login).")
        selector = page.get_by_placeholder("Por favor, seleccione.").filter(visible=True).first
        selector.click()
        registros: list[dict[str, Any]] = []
        with page.expect_response(lambda r: API_REGISTROS in r.url, timeout=30_000) as info:
            page.locator(".el-select-dropdown").filter(visible=True).get_by_text(
                periodo, exact=True
            ).first.click()
        datos = info.value.json()["ResponseStatus"]["Data"]
        registros += datos.get("OnOffDutyRecord") or []
        while datos.get("NextPage") == 1:
            with page.expect_response(lambda r: API_REGISTROS in r.url, timeout=30_000) as info:
                page.locator("button.btn-next").filter(visible=True).first.click()
            datos = info.value.json()["ResponseStatus"]["Data"]
            registros += datos.get("OnOffDutyRecord") or []

    print(f"registros: {len(registros)}")
    if not registros:
        return
    tipos = {k: type(v).__name__ for k, v in registros[0].items()}
    print(f"campos del registro: {json.dumps(tipos, ensure_ascii=False)}")
    listas = [k for k, t in tipos.items() if t == "list"]
    for k in listas:
        largos = Counter(len(r.get(k) or []) for r in registros)
        print(f"lista anidada {k!r}: distribución de largos {dict(sorted(largos.items()))}")
        sub = next((r[k][0] for r in registros if r.get(k)), None)
        if isinstance(sub, dict):
            subtipos = {sk: type(sv).__name__ for sk, sv in sub.items()}
            print(f"  campos de cada elemento: {json.dumps(subtipos, ensure_ascii=False)}")
    por_fecha = Counter(fecha_de(r) for r in registros)
    print("registros por fecha:")
    for f in sorted(por_fecha):
        anidados = {
            k: sum(len(r.get(k) or []) for r in registros if fecha_de(r) == f) for k in listas
        }
        print(f"  {f}: {por_fecha[f]}  anidados={anidados}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Mes actual")
