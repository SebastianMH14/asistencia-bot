"""Verifica el localizador de "Cerrar sesión" con un clic de prueba (no cierra la sesión).

Uso: uv run --no-sync python exploracion/diagnostico_logout.py
"""

from cdp import _pagina
from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        page = _pagina(p)
        disparador = page.locator("div[role='button'][title='admin']").filter(visible=True)
        print(f"disparador del menú admin visibles: {disparador.count()}")
        disparador.first.hover()
        page.wait_for_timeout(800)
        opcion = (
            page.locator(".el-dropdown-menu")
            .filter(visible=True)
            .get_by_text("Cerrar sesión", exact=True)
        )
        print(f"'Cerrar sesión' visibles: {opcion.count()}")
        opcion.first.click(trial=True)
        print("'Cerrar sesión' accionable (clic de prueba, la sesión sigue abierta)")
        page.mouse.move(800, 600)


if __name__ == "__main__":
    main()
