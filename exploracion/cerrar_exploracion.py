"""Cierra la sesión de HikCentral del Edge de exploración y cierra ese navegador.

Solo actúa sobre el Edge lanzado con --remote-debugging-port=9222 y el perfil
exploracion/perfil-edge (el navegador desechable de la Fase 1).

Uso: uv run --no-sync python exploracion/cerrar_exploracion.py
"""

import contextlib

from cdp import CDP, _pagina
from playwright.sync_api import sync_playwright


def main() -> None:
    p = sync_playwright().start()
    try:
        page = _pagina(p)
        if not page.locator("button.login-btn").filter(visible=True).count():
            page.locator("div[role='button'][title='admin']").filter(visible=True).first.hover()
            page.wait_for_timeout(800)
            page.locator(".el-dropdown-menu").filter(visible=True).get_by_text(
                "Cerrar sesión", exact=True
            ).first.click()
            confirmar = page.locator(".el-message-box .el-button--primary").filter(visible=True)
            if confirmar.count():
                confirmar.first.click()
            page.get_by_placeholder("Nombre de usuario").wait_for(timeout=15_000)
            print("sesión de HikCentral cerrada")
        else:
            print("no había sesión iniciada")
        navegador = p.chromium.connect_over_cdp(CDP)
        cdp = navegador.new_browser_cdp_session()
        cdp.send("Browser.close")
        print("Edge de exploración cerrado")
    finally:
        with contextlib.suppress(Exception):
            p.stop()


if __name__ == "__main__":
    main()
