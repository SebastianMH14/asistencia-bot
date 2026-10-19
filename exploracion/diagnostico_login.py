"""Diagnóstico de los campos del login en un contexto aislado del Edge de exploración.

No escribe nada ni inicia sesión: solo informa atributos y estado (visible, editable)
de los campos con placeholder "Nombre de usuario" y "Contraseña".

Uso: uv run --no-sync python exploracion/diagnostico_login.py
"""

import json

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
ATRIBUTOS = ("type", "readonly", "disabled", "autocomplete", "name", "id", "class", "tabindex")


def main() -> None:
    with sync_playwright() as p:
        navegador = p.chromium.connect_over_cdp(CDP)
        aislado = navegador.new_context(ignore_https_errors=True)
        try:
            pag = aislado.new_page()
            pag.goto("https://127.0.0.1/#/", wait_until="domcontentloaded")
            pag.get_by_placeholder("Nombre de usuario").first.wait_for(timeout=30_000)
            pag.wait_for_timeout(1500)
            for placeholder in ("Nombre de usuario", "Contraseña"):
                loc = pag.get_by_placeholder(placeholder)
                print(f"placeholder {placeholder!r}: {loc.count()} coincidencias")
                for i in range(loc.count()):
                    el = loc.nth(i)
                    attrs = {a: el.get_attribute(a) for a in ATRIBUTOS}
                    estado = {
                        "visible": el.is_visible(),
                        "habilitado": el.is_enabled(),
                        "editable": el.is_editable() if el.is_visible() else None,
                    }
                    print(f"  #{i} {json.dumps(estado)} {json.dumps(attrs, ensure_ascii=False)}")
            # ¿Quita el readonly al recibir foco?
            usuario = pag.get_by_placeholder("Nombre de usuario").filter(visible=True).first
            usuario.click()
            pag.wait_for_timeout(500)
            print(
                f"tras clic en usuario: readonly={usuario.get_attribute('readonly')!r} "
                f"editable={usuario.is_editable()}"
            )
            clave = pag.get_by_placeholder("Contraseña").filter(visible=True).first
            clave.click()
            pag.wait_for_timeout(500)
            print(
                f"tras clic en contraseña: readonly={clave.get_attribute('readonly')!r} "
                f"editable={clave.is_editable()}"
            )
        finally:
            aislado.close()


if __name__ == "__main__":
    main()
