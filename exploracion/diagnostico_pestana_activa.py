"""Nombre accesible de la pestaña "Asistencia" cuando está activa, y localizador alternativo.

Solo lee y hace clics de prueba (trial). Uso:
  uv run --no-sync python exploracion/diagnostico_pestana_activa.py
"""

from cdp import _pagina
from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        page = _pagina(p)
        pestanas = page.get_by_role("tab").filter(has_text="Asistencia").filter(visible=True)
        for i in range(pestanas.count()):
            t = pestanas.nth(i)
            print(
                f"#{i} texto={t.inner_text().strip()!r} clase={t.get_attribute('class')!r} "
                f"aria-label={t.get_attribute('aria-label')!r}"
            )
        exacto = page.get_by_role("tab", name="Asistencia", exact=True).filter(visible=True)
        print(f"get_by_role exact: {exacto.count()}")
        alternativo = (
            page.locator("[role='tab'].el-tabs__item")
            .filter(has=page.get_by_text("Asistencia", exact=True))
            .filter(visible=True)
        )
        print(f"alternativo (tab que contiene el texto exacto): {alternativo.count()}")
        if alternativo.count():
            alternativo.first.click(trial=True)
            print("alternativo accionable")


if __name__ == "__main__":
    main()
