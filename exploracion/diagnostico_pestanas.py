"""Compara get_by_role("tab", name="Asistencia") con y sin exact=True desde la página de inicio.

Solo navega (inicio → Asistencia); no cambia nada.

Uso: uv run --no-sync python exploracion/diagnostico_pestanas.py
"""

from cdp import _pagina
from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        page = _pagina(p)
        page.locator("span.home-icon-wrap").filter(visible=True).first.click()
        page.wait_for_timeout(2500)
        sin_exact = page.get_by_role("tab", name="Asistencia")
        con_exact = page.get_by_role("tab", name="Asistencia", exact=True)
        print(f"en inicio: sin exact={sin_exact.count()}  con exact={con_exact.count()}")
        for i in range(sin_exact.count()):
            print(f"  coincidencia sin exact #{i}: {sin_exact.nth(i).inner_text().strip()!r}")
        nueva = con_exact.filter(visible=True).first
        nueva.click(trial=True)
        print("localizador nuevo accionable desde inicio")
        nueva.click()
        page.wait_for_timeout(1500)
        print(
            f"de vuelta en Asistencia; botón Exportar visible: "
            f"{page.locator('button.export-btn').filter(visible=True).count()}"
        )


if __name__ == "__main__":
    main()
