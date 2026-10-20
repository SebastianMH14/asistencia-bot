"""Compara por persona (anonimizada) la consulta de la interfaz con un Excel exportado.

Reutiliza la navegación de comparar_por_fecha.py. Los identificadores se usan solo en
memoria para cruzar el Excel con la API; se imprime solo:
- nombres de los campos de BaseInfo (sin valores),
- qué campo de BaseInfo coincide con la columna "ID" del Excel (tamaño de la intersección),
- por cada persona con diferencias: una etiqueta anónima (A, B, …), conteos y fechas.

Uso:
  uv run --no-sync python exploracion/comparar_por_persona.py <ruta.xlsx> \
      [--periodo "Mes actual"] [--grupo Fisioterapeutas]
"""

import argparse
import json
import string
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from cdp import _pagina
from comparar_por_fecha import (
    API_REGISTROS,
    elegir_grupo,
    elegir_periodo,
    fecha_de,
    ir_al_reporte,
)
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright


def filas_excel(ruta: Path) -> list[tuple[str, str]]:
    """(ID, Fecha) de cada fila de datos."""
    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        hoja = libro[libro.sheetnames[0]]
        cab: list[str] = []
        salida: list[tuple[str, str]] = []
        for fila in hoja.iter_rows(values_only=True):
            textos = [str(c).strip() if c is not None else "" for c in fila]
            if not cab:
                if "Fecha" in textos and "Departamento" in textos:
                    cab = textos
                continue
            if any(textos):
                salida.append((textos[cab.index("ID")], textos[cab.index("Fecha")]))
        return salida
    finally:
        libro.close()


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("excel", type=Path)
    a.add_argument("--periodo", default="Mes actual")
    a.add_argument("--grupo", default="Fisioterapeutas")
    args = a.parse_args()

    registros: list[dict[str, Any]] = []
    with sync_playwright() as p:
        page = _pagina(p)
        ir_al_reporte(page)
        elegir_periodo(page, args.periodo)
        respuesta = elegir_grupo(page, args.grupo)
        while True:
            datos = respuesta.json()["ResponseStatus"]["Data"]
            registros += datos.get("OnOffDutyRecord") or []
            if datos.get("NextPage") != 1:
                break
            with page.expect_response(lambda r: API_REGISTROS in r.url, timeout=30_000) as info:
                page.locator("button.btn-next").filter(visible=True).first.click()
            respuesta = info.value

    excel = filas_excel(args.excel)
    ids_excel = {i for i, _ in excel}
    persona0 = registros[0]["BaseInfo"].get("PersonInfo") or {}
    print(f"campos de BaseInfo.PersonInfo: {sorted(persona0.keys())}")

    def valor(r: dict[str, Any], campo: str) -> str:
        return str((r["BaseInfo"].get("PersonInfo") or {}).get(campo, "")).strip()

    # Qué subcampo de PersonInfo coincide con la columna ID del Excel (solo tamaños).
    mejor, mejor_n = "", -1
    for campo in persona0:
        n = len({valor(r, campo) for r in registros} & ids_excel)
        print(f"  PersonInfo.{campo}: {n} de {len(ids_excel)} IDs del Excel coinciden")
        if n > mejor_n:
            mejor, mejor_n = campo, n
    if mejor_n <= 0:
        print("Ningún campo de PersonInfo coincide con el ID del Excel; no se puede cruzar.")
        return
    print(f"campo de cruce: PersonInfo.{mejor}")

    fechas_distintas = sum(
        1 for r in registros if str(r["BaseInfo"].get("Date", ""))[:10] != fecha_de(r)
    )
    print(f"registros cuya fecha de entrada/salida difiere de BaseInfo.Date: {fechas_distintas}")

    api_por_persona: dict[str, Counter[str]] = defaultdict(Counter)
    for r in registros:
        api_por_persona[valor(r, mejor)][str(r["BaseInfo"].get("Date", ""))[:10]] += 1
    excel_por_persona: dict[str, Counter[str]] = defaultdict(Counter)
    for i, f in excel:
        excel_por_persona[i][f] += 1

    print(f"personas en el Excel: {len(excel_por_persona)}; en la consulta: {len(api_por_persona)}")
    etiquetas = iter(string.ascii_uppercase)
    for persona in sorted(set(api_por_persona) | set(excel_por_persona)):
        e, c = excel_por_persona.get(persona, Counter()), api_por_persona.get(persona, Counter())
        if e == c:
            continue
        fechas = sorted(set(e) | set(c))
        detalle = {
            f: f"excel={e.get(f, 0)} consulta={c.get(f, 0)}"
            for f in fechas
            if e.get(f, 0) != c.get(f, 0)
        }
        print(
            f"persona {next(etiquetas)}: excel={sum(e.values())} consulta={sum(c.values())}; "
            f"en consulta: {'sí' if persona in api_por_persona else 'no'}; "
            f"diferencias: {json.dumps(detalle, ensure_ascii=False)}"
        )


if __name__ == "__main__":
    main()
