"""Prueba controlada: ¿la paginación de la consulta pierde registros en el corte de página?

En la sesión de exploración (con el grupo ya seleccionado), elige el periodo, cambia el
tamaño de página de la tabla, recorre las páginas sumando registros y vuelve a 100.
El tamaño de página es un control de vista de la tabla, no configuración de HikCentral.
Solo imprime números.

Uso: uv run --no-sync python exploracion/prueba_tamano_pagina.py --periodo "Última semana" --tamano 50
"""

import argparse
import contextlib
import json

from cdp import _pagina
from comparar_por_fecha import API_REGISTROS, elegir_periodo
from playwright.sync_api import Page, Response, sync_playwright


def cambiar_tamano(page: Page, tamano: int) -> Response:
    selector = page.get_by_placeholder("Por favor, seleccione.").filter(visible=True)
    valores = [selector.nth(i).input_value() for i in range(selector.count())]
    indice = next(i for i, v in enumerate(valores) if v.isdigit())
    page.wait_for_timeout(800)  # deja que se cierre la lista anterior
    selector.nth(indice).click()
    opcion = (
        page.locator(".el-select-dropdown__item")
        .filter(visible=True)
        .filter(has=page.get_by_text(f"{tamano}", exact=True))
    )
    opcion.first.wait_for(timeout=10_000)
    with page.expect_response(lambda r: API_REGISTROS in r.url, timeout=30_000) as info:
        opcion.first.click()
    return info.value


def recorrer(page: Page, primera: Response) -> list[dict[str, int]]:
    paginas = []
    respuesta = primera
    while True:
        consulta = json.loads(respuesta.request.post_data or "{}")["RecordRequest"]
        datos = respuesta.json()["ResponseStatus"]["Data"]
        paginas.append(
            {
                "pedida": consulta["PageIndex"],
                "tamano": consulta["PageSize"],
                "registros": len(datos.get("OnOffDutyRecord") or []),
                "NextPage": datos.get("NextPage"),
            }
        )
        if datos.get("NextPage") != 1:
            return paginas
        with page.expect_response(lambda r: API_REGISTROS in r.url, timeout=30_000) as info:
            page.locator("button.btn-next").filter(visible=True).first.click()
        respuesta = info.value


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("--periodo", default="Última semana")
    a.add_argument("--tamano", type=int, default=50)
    args = a.parse_args()
    p = sync_playwright().start()
    try:
        page = _pagina(p)
        seleccion = (
            page.locator("button").filter(has_text="personas seleccionadas").filter(visible=True)
        )
        print(f"selección: {seleccion.first.inner_text().strip()!r}", flush=True)
        elegir_periodo(page, args.periodo)
        paginas: list[dict[str, int]] = []
        try:
            paginas = recorrer(page, cambiar_tamano(page, args.tamano))
        except BaseException as e:
            print(f"ERROR {type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}")
        finally:
            cambiar_tamano(page, 100)
            print("tamaño de página devuelto a 100", flush=True)
        for pg in paginas:
            print(f"  {pg}")
        suma = sum(pg["registros"] for pg in paginas)
        print(f"periodo {args.periodo!r}, páginas de {args.tamano}: suma = {suma}", flush=True)
    finally:
        # El cierre de la conexión CDP a veces choca con el event loop; no afecta.
        with contextlib.suppress(RuntimeError):
            p.stop()


if __name__ == "__main__":
    main()
