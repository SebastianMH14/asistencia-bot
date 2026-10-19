"""Cuenta los registros de la consulta de la tabla en la sesión de exploración (solo longitudes).

Usa la selección de personas que ya tenga la pantalla, elige el periodo indicado y recorre
las páginas con el botón "siguiente", sumando las longitudes de OnOffDutyRecord.
No exporta ni imprime datos de personas.

Uso: uv run --no-sync python exploracion/contar_consulta.py "Mes anterior"
"""

import json
import sys

from cdp import _pagina
from playwright.sync_api import sync_playwright

API_REGISTROS = "/ISAPI/Bumblebee/AttendancePlugin/V1/Record"


def main(periodo: str) -> None:
    with sync_playwright() as p:
        page = _pagina(p)
        boton = (
            page.locator("button").filter(has_text="personas seleccionadas").filter(visible=True)
        )
        print(f"selección actual: {boton.first.inner_text().strip()!r}")
        selector = page.get_by_placeholder("Por favor, seleccione.").filter(visible=True).first
        selector.click()
        with page.expect_response(lambda r: API_REGISTROS in r.url, timeout=30_000) as info:
            page.locator(".el-select-dropdown").filter(visible=True).get_by_text(
                periodo, exact=True
            ).first.click()
        consulta = json.loads(info.value.request.post_data or "{}")["RecordRequest"]["QueryInfo"]
        datos = info.value.json()["ResponseStatus"]["Data"]
        total, paginas = len(datos.get("OnOffDutyRecord") or []), 1
        while datos.get("NextPage") == 1:
            with page.expect_response(lambda r: API_REGISTROS in r.url, timeout=30_000) as info:
                page.locator("button.btn-next").filter(visible=True).first.click()
            datos = info.value.json()["ResponseStatus"]["Data"]
            total += len(datos.get("OnOffDutyRecord") or [])
            paginas += 1
        print(
            f"periodo {periodo!r}: {consulta['BeginTime']} → {consulta['EndTime']}; "
            f"personas={len(consulta['PersonID'])}; registros={total} en {paginas} página(s)"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Última semana")
