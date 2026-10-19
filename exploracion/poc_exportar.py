"""Prueba de concepto (Fase 1): exporta un grupo de HikCentral y captura el Excel.

La ejecuta el USUARIO en su terminal: toma la contraseña de keyring y la escribe en
HikCentral (login y confirmación de exportación). Claude no la ejecuta.

Solo imprime pasos, tiempos, conteos y nombres de archivo; nunca contenido del reporte
ni la contraseña. Sin trace de Playwright: registraría el texto escrito en los campos.
Ante un error guarda solo una captura en exploracion/salida/ (local, fuera de git).

Uso (desde C:\\Users\\<usuario>\\asistencia-bot):
  .venv\\Scripts\\python.exe exploracion\\poc_exportar.py
  .venv\\Scripts\\python.exe exploracion\\poc_exportar.py --headless
  .venv\\Scripts\\python.exe exploracion\\poc_exportar.py --periodo "Mes anterior"
"""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, Response, Route, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

sys.path.insert(0, str(Path(__file__).parent))
from validar_excel import inspeccionar

from asistencia_bot.adapters.credenciales_keyring import AlmacenKeyring

URL = "https://127.0.0.1/#/"
HOSTS_PERMITIDOS = {"127.0.0.1", "localhost"}
DOWNLOADCENTER = Path(r"C:\Users\<usuario>\HCWebControlService\Downloadcenter")
REPORTE = "Registros de entradas y salidas"
API_REGISTROS = "/ISAPI/Bumblebee/AttendancePlugin/V1/Record"
SALIDA = Path(__file__).parent / "salida"
ZONA = ZoneInfo("America/Bogota")
T0 = time.monotonic()


def paso(mensaje: str) -> None:
    print(f"[{time.monotonic() - T0:6.1f}s] {mensaje}", flush=True)


def exacto(texto: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(texto)}\s*$")


def periodo_esperado(nombre: str, hoy: date) -> tuple[date, date] | None:
    if nombre == "Última semana":
        desde = hoy - timedelta(days=hoy.weekday() + 7)
        return desde, desde + timedelta(days=6)
    if nombre == "Mes anterior":
        hasta = hoy.replace(day=1) - timedelta(days=1)
        return hasta.replace(day=1), hasta
    return None


def solo_local(route: Route) -> None:
    url = route.request.url
    if url.startswith(("data:", "blob:")) or urlparse(url).hostname in HOSTS_PERMITIDOS:
        route.continue_()
    else:
        paso(f"bloqueada una petición a un host externo: {urlparse(url).hostname}")
        route.abort()


def textos_visibles(page: Page, selector: str) -> list[str]:
    loc = page.locator(selector).filter(visible=True)
    return [" ".join(t.split())[:120] for t in loc.all_inner_texts() if t.strip()]


def cerrar_aviso(page: Page) -> None:
    ok = page.locator("button.refresh-know").filter(visible=True)
    if ok.count():
        ok.first.click()
        paso("aviso de actualización cerrado con OK")


def iniciar_sesion(page: Page, usuario: str, clave: str) -> None:
    page.goto(URL, wait_until="domcontentloaded")
    page.get_by_placeholder("Nombre de usuario").wait_for(timeout=30_000)
    page.get_by_role("tab", name="Administración").click()
    # El campo de usuario trae readonly (anti-autocompletado) que se quita al recibir el foco.
    campo_usuario = page.get_by_placeholder("Nombre de usuario")
    campo_usuario.click()
    campo_usuario.fill(usuario)
    campo_clave = page.get_by_placeholder("Contraseña")
    campo_clave.click()
    campo_clave.fill(clave)
    page.get_by_role("button", name="Iniciar sesión").click()
    try:
        page.get_by_role("tab", name="Asistencia").wait_for(timeout=45_000)
    except PlaywrightTimeout:
        mensajes = textos_visibles(page, ".el-message, .el-message-box, .el-form-item__error")
        raise RuntimeError(f"no se completó el inicio de sesión; mensajes: {mensajes}") from None
    paso("sesión iniciada")
    titulos = textos_visibles(page, ".el-dialog__title, .el-message-box__title, .el-drawer__title")
    if titulos:
        paso(f"diálogos visibles tras el login: {titulos}")


def ir_al_reporte(page: Page) -> None:
    page.get_by_role("tab", name="Asistencia").click()
    page.wait_for_timeout(1500)
    cerrar_aviso(page)
    item = page.locator("ul.el-menu li.el-menu-item").filter(has_text=exacto(REPORTE))
    if not item.filter(visible=True).count():
        page.locator(".el-submenu__title").filter(has_text=exacto("Registro de asistencia")).filter(
            visible=True
        ).first.click()
    item.filter(visible=True).first.click()
    page.locator("button.export-btn").filter(visible=True).first.wait_for(timeout=30_000)
    cerrar_aviso(page)
    paso(f"en '{REPORTE}'")


def elegir_periodo(page: Page, periodo: str) -> None:
    selector = page.get_by_placeholder("Por favor, seleccione.").filter(visible=True).first
    selector.click()
    page.locator(".el-select-dropdown__item").filter(visible=True).filter(
        has_text=exacto(periodo)
    ).first.click()
    page.wait_for_timeout(1000)
    paso(f"periodo elegido: {selector.input_value()!r}")


def elegir_grupo(page: Page, departamento: str) -> tuple[int, Response]:
    page.locator("button").filter(has_text=re.compile(r"personas seleccionadas\s*$", re.I)).filter(
        visible=True
    ).first.click()
    page.locator(f"li[class*='level'] a[title='{departamento}']").filter(visible=True).first.click()
    page.wait_for_timeout(1000)
    todos = (
        page.locator("label.el-checkbox")
        .filter(has_text="Seleccionar todos")
        .filter(visible=True)
        .first
    )
    if "is-checked" not in (todos.get_attribute("class") or ""):
        todos.click()
    with page.expect_response(lambda r: API_REGISTROS in r.url, timeout=30_000) as info:
        page.locator("button[title='Aceptar']").filter(visible=True).first.click()
    boton = (
        page.locator("button")
        .filter(has_text=re.compile(r"^\s*\d+ personas seleccionadas"))
        .filter(visible=True)
        .first
    )
    personas = int(re.search(r"\d+", boton.inner_text()).group())  # type: ignore[union-attr]
    paso(f"grupo '{departamento}': {personas} personas seleccionadas")
    return personas, info.value


def contar_registros(page: Page, primera: Response) -> tuple[int, int, str]:
    """Suma los registros de todas las páginas de la consulta (solo longitudes)."""
    consulta = json.loads(primera.request.post_data or "{}")["RecordRequest"]["QueryInfo"]
    rango = f"{consulta['BeginTime']} → {consulta['EndTime']}"
    datos = primera.json()["ResponseStatus"]["Data"]
    total, paginas = len(datos.get("OnOffDutyRecord") or []), 1
    while datos.get("NextPage") == 1:
        with page.expect_response(lambda r: API_REGISTROS in r.url, timeout=30_000) as info:
            page.locator("button.btn-next").filter(visible=True).first.click()
        datos = info.value.json()["ResponseStatus"]["Data"]
        total += len(datos.get("OnOffDutyRecord") or [])
        paginas += 1
    for _ in range(paginas - 1):  # volver a la página 1 antes de exportar
        page.locator("button.btn-prev").filter(visible=True).first.click()
        page.wait_for_timeout(700)
    paso(f"consulta de la interfaz: {total} registros en {paginas} página(s); rango {rango}")
    return total, paginas, rango


def esperar_archivo(antes: set[str], nombre: str | None, limite_s: float) -> Path:
    fin = time.monotonic() + limite_s
    tamanos: dict[Path, int] = {}
    estables: dict[Path, int] = {}
    while time.monotonic() < fin:
        for carpeta in DOWNLOADCENTER.iterdir():
            if carpeta.name in antes or not carpeta.name.startswith(f"{REPORTE}_"):
                continue
            for archivo in carpeta.glob("*.xlsx"):
                if nombre and archivo.name != nombre:
                    continue
                tam = archivo.stat().st_size
                estables[archivo] = (
                    estables.get(archivo, 0) + 1 if tamanos.get(archivo) == tam else 0
                )
                tamanos[archivo] = tam
                if estables[archivo] >= 3:
                    return archivo
        time.sleep(0.5)
    raise TimeoutError(f"no apareció un archivo estable en {limite_s:.0f} s")


def exportar(page: Page, clave: str, nombre: str | None) -> tuple[Path, bool]:
    antes = {p.name for p in DOWNLOADCENTER.iterdir()}
    eventos_descarga: list[str] = []
    page.on("download", lambda d: eventos_descarga.append(d.suggested_filename))
    page.locator("button.export-btn").filter(visible=True).first.click()
    panel = page.get_by_role("dialog", name="Configuración a exportar")
    panel.wait_for(timeout=15_000)
    panel.get_by_role("radio", name="Excel").click()
    modo = panel.get_by_placeholder("Predefinido").input_value()
    if modo != "Predefinido":
        raise RuntimeError(f"modo monitor inesperado: {modo!r}")
    campo_clave = panel.get_by_placeholder("Contraseña")
    campo_clave.click()
    campo_clave.fill(clave)
    t_clic = time.monotonic()
    panel.get_by_role("button", name="Exportar", exact=True).click()
    page.wait_for_timeout(1500)
    errores = textos_visibles(page, ".el-message--error, .el-form-item__error")
    if errores:
        raise RuntimeError(f"la interfaz mostró un error al exportar: {errores}")
    archivo = esperar_archivo(antes, nombre, limite_s=120)
    paso(
        f"archivo estable a los {time.monotonic() - t_clic:.1f} s del clic: {archivo.parent.name}\\{archivo.name}"
    )
    page.wait_for_timeout(2000)
    return archivo, bool(eventos_descarga)


def cerrar_sesion(page: Page, usuario: str) -> None:
    try:
        page.locator(f"div[role='button'][title='{usuario}']").filter(visible=True).first.hover()
        page.locator("li.el-dropdown-menu__item").filter(has_text=exacto("Cerrar sesión")).filter(
            visible=True
        ).first.click(timeout=5_000)
        confirmar = page.locator(".el-message-box .el-button--primary").filter(visible=True)
        if confirmar.count():
            confirmar.first.click()
        page.get_by_placeholder("Nombre de usuario").wait_for(timeout=15_000)
        paso("sesión cerrada")
    except Exception as e:
        paso(f"no se pudo cerrar sesión: {type(e).__name__}")


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument("--grupo", default="Fisioterapeutas", help="departamento en HikCentral")
    analizador.add_argument("--periodo", default="Última semana")
    analizador.add_argument("--usuario", default="admin")
    analizador.add_argument("--navegador", default="msedge", choices=["msedge", "chrome"])
    analizador.add_argument("--headless", action="store_true")
    args = analizador.parse_args()

    clave = AlmacenKeyring().obtener("hikcentral", args.usuario)
    if not clave:
        print(
            "No hay contraseña en keyring. Ejecuta primero:\n"
            f"  .venv\\Scripts\\asistencia-bot.exe credenciales configurar hikcentral -u {args.usuario}"
        )
        return 2

    hoy = datetime.now(ZONA).date()
    esperado = periodo_esperado(args.periodo, hoy)
    nombre = f"{REPORTE}_{esperado[0]}_{esperado[1]}.xlsx" if esperado else None
    modo = "headless" if args.headless else "visible"
    paso(f"PoC: grupo={args.grupo!r} periodo={args.periodo!r} navegador={args.navegador} ({modo})")

    SALIDA.mkdir(exist_ok=True)
    with sync_playwright() as p:
        navegador = p.chromium.launch(channel=args.navegador, headless=args.headless)
        contexto = navegador.new_context(
            ignore_https_errors=True, viewport={"width": 1600, "height": 900}, locale="es-ES"
        )
        contexto.route("**/*", solo_local)
        page = contexto.new_page()
        try:
            iniciar_sesion(page, args.usuario, clave)
            ir_al_reporte(page)
            elegir_periodo(page, args.periodo)
            personas, primera = elegir_grupo(page, args.grupo)
            total_api, paginas, _ = contar_registros(page, primera)
            archivo, hubo_evento = exportar(page, clave, nombre)
            cerrar_sesion(page, args.usuario)
        except Exception as e:
            captura = SALIDA / f"poc_error_{datetime.now():%Y%m%d_%H%M%S}.png"
            page.screenshot(path=captura)
            primera_linea = str(e).splitlines()[0][:300] if str(e) else ""
            paso(f"ERROR {type(e).__name__}: {primera_linea}")
            paso(f"captura local (sensible, no compartir): {captura}")
            return 2
        finally:
            navegador.close()

    e = inspeccionar(archivo)
    esperado_txt = f"Periodo: {esperado[0]} - {esperado[1]}" if esperado else None
    chequeos = {
        "periodo": (e.periodo == esperado_txt) if esperado_txt else None,
        "departamentos": e.departamentos == {f"General>{args.grupo}"},
        "filas_igual_interfaz": e.filas_datos == total_api,
    }
    resumen = {
        "archivo": e.archivo,
        "tamano_b": e.tamano,
        "sha256": e.sha256,
        "periodo_excel": e.periodo,
        "departamentos": sorted(e.departamentos),
        "filas_excel": e.filas_datos,
        "registros_interfaz": total_api,
        "paginas_interfaz": paginas,
        "personas_seleccionadas": personas,
        "evento_download_playwright": hubo_evento,
        "modo": modo,
        "chequeos": chequeos,
        "duracion_s": round(time.monotonic() - T0, 1),
    }
    print("RESUMEN " + json.dumps(resumen, ensure_ascii=False))
    return 0 if all(v is not False for v in chequeos.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
