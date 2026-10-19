"""Verifica localizadores del panel de exportación en la sesión de exploración.

Abre el panel con el botón Exportar si no está abierto, compara localizadores y lo
cierra con Cancelar. No escribe la contraseña ni exporta.

Uso: uv run --no-sync python exploracion/diagnostico_exportar.py
"""

import json

from cdp import _pagina
from playwright.sync_api import sync_playwright

CSS_PANEL = "[role='dialog'][aria-label='Configuración a exportar']"

JS_ARIA = """e => {
  const anc = [];
  for (let n = e; n; n = n.parentElement) {
    if (n.getAttribute && n.getAttribute('aria-hidden') !== null) {
      anc.push(n.tagName + '.' + String(n.className || '').split(' ')[0]
               + ' aria-hidden=' + n.getAttribute('aria-hidden'));
    }
  }
  return {aria_modal: e.getAttribute('aria-modal'),
          labelledby: e.getAttribute('aria-labelledby'),
          ancestros_aria_hidden: anc};
}"""


def main() -> None:
    with sync_playwright() as p:
        page = _pagina(p)
        css = page.locator(CSS_PANEL).filter(visible=True)
        if not css.count():
            page.locator("button.export-btn").filter(visible=True).first.click()
            css.first.wait_for(timeout=10_000)
        print(f"CSS {CSS_PANEL} visibles: {css.count()}")
        print(f"atributos: {json.dumps(css.first.evaluate(JS_ARIA), ensure_ascii=False)}")
        print(
            "get_by_role(dialog, name) visibles: "
            f"{page.get_by_role('dialog', name='Configuración a exportar').count()}"
        )
        print(
            "get_by_role(dialog, name, include_hidden=True): "
            f"{page.get_by_role('dialog', name='Configuración a exportar', include_hidden=True).count()}"
        )
        panel = css.first
        excel = panel.locator("label[title='Excel']").filter(visible=True)
        modo = panel.get_by_placeholder("Predefinido").filter(visible=True)
        clave = panel.get_by_placeholder("Contraseña").filter(visible=True)
        exportar = panel.locator("button[title='Exportar']").filter(visible=True)
        cancelar = panel.locator("button[title='Cancelar']").filter(visible=True)
        print(
            f"radio Excel visibles: {excel.count()} (clase: {excel.first.get_attribute('class')})"
        )
        print(f"modo visibles: {modo.count()} valor={modo.first.input_value()!r}")
        print(f"contraseña visibles: {clave.count()} editable={clave.first.is_editable()}")
        print(f"Exportar visibles: {exportar.count()}  Cancelar visibles: {cancelar.count()}")
        exportar.first.click(trial=True)
        print("Exportar accionable (clic de prueba, no exporta)")
        cancelar.first.click()
        page.wait_for_timeout(800)
        print(f"panel cerrado: {css.count() == 0}")


if __name__ == "__main__":
    main()
