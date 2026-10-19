"""Compara localizadores del menú lateral de Asistencia sobre la sesión de exploración.

No hace clics reales: cuenta coincidencias y usa click(trial=True), que solo verifica
si el elemento es accionable.

Uso: uv run --no-sync python exploracion/diagnostico_menu.py
"""

import re

from playwright.sync_api import Locator, sync_playwright

from cdp import _pagina

REPORTE = "Registros de entradas y salidas"
SUBMENU = "Registro de asistencia"


def exacto(texto: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(texto)}\s*$")


def informar(nombre: str, loc: Locator) -> None:
    total = loc.count()
    visibles = loc.filter(visible=True).count()
    accionable = "—"
    if visibles:
        try:
            loc.filter(visible=True).first.click(trial=True, timeout=3_000)
            accionable = "sí"
        except Exception as e:
            accionable = f"no ({type(e).__name__})"
    print(f"{nombre:<55} total={total} visibles={visibles} accionable={accionable}")


def main() -> None:
    with sync_playwright() as p:
        page = _pagina(p)
        informar(
            "PoC: li.el-menu-item has_text=regex exacto",
            page.locator("ul.el-menu li.el-menu-item").filter(has_text=exacto(REPORTE)),
        )
        informar(
            "li.el-menu-item has_text=substring",
            page.locator("ul.el-menu li.el-menu-item").filter(has_text=REPORTE),
        )
        informar(
            "ul.el-menu >> get_by_text(exact=True)",
            page.locator("ul.el-menu").get_by_text(REPORTE, exact=True),
        )
        informar(
            "li.el-menu-item_attendanceStaffCommutingReport",
            page.locator("li.el-menu-item_attendanceStaffCommutingReport"),
        )
        informar(
            "PoC: .el-submenu__title has_text=regex exacto",
            page.locator(".el-submenu__title").filter(has_text=exacto(SUBMENU)),
        )
        informar(
            "ul.el-menu >> get_by_text(submenú, exact=True)",
            page.locator("ul.el-menu").get_by_text(SUBMENU, exact=True),
        )
        li = page.locator("ul.el-menu li.el-menu-item").filter(has_text=REPORTE).first
        if li.count():
            texto = li.evaluate("e => JSON.stringify(e.textContent)")
            print(f"textContent del li: {texto}")


if __name__ == "__main__":
    main()
