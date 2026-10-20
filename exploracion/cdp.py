"""Explorador de HikCentral sobre el Edge de exploración (depuración remota en 127.0.0.1:9222).

El usuario inicia sesión en ese Edge; este script nunca escribe contraseñas.
Solo lista controles y navega. No imprime filas de tablas (contienen datos personales).

Uso: uv run --frozen python exploracion/cdp.py <comando> [argumentos]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Locator, Page, WebSocket, sync_playwright

CDP = "http://127.0.0.1:9222"

# Lista elementos clicables o de formulario visibles, sin entrar en cuerpos de tabla.
JS_CONTROLES = r"""
(raiz) => {
  const dentroDeTabla = (el) => !!el.closest(
    'tbody, .el-table__body-wrapper, [class*="table-body"], [class*="tableBody"]');
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const textoPropio = (el) => (el.innerText || el.value || '').trim().replace(/\s+/g, ' ');
  const nativos = 'button, a, input, select, textarea, label, [role], [tabindex]';
  const salida = [];
  const vistos = new Set();
  for (const el of raiz.querySelectorAll('*')) {
    if (!visible(el) || dentroDeTabla(el)) continue;
    const s = getComputedStyle(el);
    const padre = el.parentElement;
    const puntero = s.cursor === 'pointer' && !(padre && getComputedStyle(padre).cursor === 'pointer');
    if (!el.matches(nativos) && !puntero) continue;
    const texto = textoPropio(el).slice(0, 70);
    const r = el.getBoundingClientRect();
    const clave = [el.tagName, el.getAttribute('role'), texto, Math.round(r.x), Math.round(r.y)].join('|');
    if (vistos.has(clave)) continue;
    vistos.add(clave);
    salida.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      type: el.getAttribute('type') || '',
      texto,
      aria: el.getAttribute('aria-label') || '',
      placeholder: el.getAttribute('placeholder') || '',
      title: el.getAttribute('title') || '',
      clase: (el.className && typeof el.className === 'string') ? el.className.split(/\s+/).slice(0, 3).join('.') : '',
      x: Math.round(r.x), y: Math.round(r.y),
    });
  }
  return salida;
}
"""


def _pagina(p: object) -> Page:
    navegador = p.chromium.connect_over_cdp(CDP)  # type: ignore[attr-defined]
    for contexto in navegador.contexts:
        for pagina in contexto.pages:
            if "127.0.0.1" in pagina.url:
                return pagina  # type: ignore[no-any-return]
    sys.exit("No hay una pestaña de HikCentral abierta en el Edge de exploración.")


def _imprimir_controles(pagina: Page, dentro: str | None) -> None:
    raiz: Locator = pagina.locator(dentro).first if dentro else pagina.locator("body")
    controles = raiz.evaluate(JS_CONTROLES)
    for c in controles:
        partes = [f"{c['tag']}"]
        for campo in ("role", "type", "aria", "placeholder", "title"):
            if c[campo]:
                partes.append(f"{campo}={c[campo]!r}")
        if c["texto"]:
            partes.append(f"texto={c['texto']!r}")
        partes.append(f"@({c['x']},{c['y']})")
        if c["clase"]:
            partes.append(f".{c['clase']}")
        print("  ".join(partes))
    print(f"-- {len(controles)} controles")


CLAVES_NUMERICAS = ("total", "count", "size", "num", "page", "code", "error")


def _numericos(obj: object, ruta: str = "", profundidad: int = 0) -> list[str]:
    """Solo claves con valores numéricos o booleanos y longitudes de listas; nunca texto."""
    salida: list[str] = []
    if profundidad > 3:
        return salida
    if isinstance(obj, dict):
        for k, v in obj.items():
            r = f"{ruta}.{k}" if ruta else str(k)
            if isinstance(v, bool | int | float) and any(c in k.lower() for c in CLAVES_NUMERICAS):
                salida.append(f"{r}={v}")
            elif isinstance(v, list):
                salida.append(f"{r}=[{len(v)} elementos]")
            elif isinstance(v, dict):
                salida.extend(_numericos(v, r, profundidad + 1))
    return salida


CLAVES_FECHA = ("time", "date", "begin", "end", "start", "period", "page", "type", "mode")


def _fechas_y_paginas(obj: object, ruta: str = "", profundidad: int = 0) -> list[str]:
    """De la petición, solo fechas, paginación y tipos; los identificadores de personas se cuentan."""
    salida: list[str] = []
    if profundidad > 4 or not isinstance(obj, dict):
        return salida
    for k, v in obj.items():
        r = f"{ruta}.{k}" if ruta else str(k)
        if isinstance(v, dict):
            salida.extend(_fechas_y_paginas(v, r, profundidad + 1))
        elif isinstance(v, list):
            salida.append(f"{r}=[{len(v)} elementos]")
        elif any(c in k.lower() for c in CLAVES_FECHA):
            salida.append(f"{r}={v}")
    return salida


def _resumir_respuesta(resp: object) -> None:
    from playwright.sync_api import Response

    assert isinstance(resp, Response)
    if resp.request.resource_type not in ("xhr", "fetch"):
        return
    ruta = resp.url.split("?")[0].replace("https://127.0.0.1", "")
    try:
        cuerpo = resp.json()
    except Exception:
        print(f"{resp.request.method} {ruta} -> {resp.status} (no JSON)")
        return
    claves = list(cuerpo.keys())[:8] if isinstance(cuerpo, dict) else type(cuerpo).__name__
    print(f"{resp.request.method} {ruta} -> {resp.status} claves={claves}")
    try:
        peticion = json.loads(resp.request.post_data or "null")
    except ValueError:
        peticion = None
    for linea in _fechas_y_paginas(peticion):
        print(f"    petición: {linea}")
    for linea in _numericos(cuerpo):
        print(f"    {linea}")


DOWNLOADCENTER = str(Path.home() / "HCWebControlService" / "Downloadcenter")


def _metodos_ws(carga: str | bytes) -> str:
    texto = carga.decode("utf-8", "replace") if isinstance(carga, bytes) else carga
    metodos = re.findall(r'"(?:Method|method|cmd|Cmd)"\s*:\s*"([A-Za-z_]+)"', texto)
    return f"{','.join(metodos) or '(sin método)'} [{len(texto)} car.]"


def _vigilar_exportacion(pagina: Page, segundos: int) -> None:
    """Solo observa: no pulsa nada. El usuario escribe la contraseña y pulsa Exportar."""
    dc = Path(DOWNLOADCENTER)
    descargas = Path.home() / "Downloads"
    antes_dc = {p.name for p in dc.iterdir()}
    antes_dl = {p.name for p in descargas.iterdir()} if descargas.exists() else set()
    t0 = time.monotonic()

    def log(mensaje: str) -> None:
        print(f"[{time.monotonic() - t0:7.1f}s] {mensaje}", flush=True)

    def al_websocket(ws: WebSocket) -> None:
        log(f"websocket abierto: {ws.url}")
        ws.on("framesent", lambda f: log(f"  ws-> {_metodos_ws(f)}"))
        ws.on("framereceived", lambda f: log(f"  ws<- {_metodos_ws(f)}"))

    pagina.on(
        "download", lambda d: log(f"EVENTO download (estrategia a): {d.suggested_filename!r}")
    )
    pagina.on("websocket", al_websocket)
    pagina.context.on("page", lambda p: log(f"nueva pestaña: {p.url[:80]}"))
    pagina.on("response", lambda r: _resumir_respuesta(r))

    log(f"vigilando {dc} y {descargas}; esperando a que se pulse Exportar")
    vistos: set[str] = set()
    tamanos: dict[str, int] = {}
    estables: dict[str, int] = {}
    fin: float | None = None
    while time.monotonic() - t0 < segundos:
        pagina.wait_for_timeout(500)
        for carpeta in sorted(p for p in dc.iterdir() if p.name not in antes_dc):
            if carpeta.name not in vistos:
                vistos.add(carpeta.name)
                log(f"carpeta nueva en Downloadcenter: {carpeta.name}")
            if carpeta.is_dir():
                for archivo in carpeta.iterdir():
                    clave = str(archivo)
                    tam = archivo.stat().st_size
                    if clave not in tamanos:
                        log(f"archivo nuevo: {archivo.name} ({tam} B)")
                    elif tam != tamanos[clave]:
                        log(f"  crece: {tam} B")
                        estables[clave] = 0
                    else:
                        estables[clave] = estables.get(clave, 0) + 1
                        if estables[clave] == 3:
                            log(f"ESTABLE (3 sondeos): {archivo.name} {tam} B")
                            fin = fin or time.monotonic() + 8
                    tamanos[clave] = tam
        if descargas.exists():
            for p in descargas.iterdir():
                if p.name not in antes_dl and p.name not in vistos:
                    vistos.add(p.name)
                    log(f"archivo nuevo en Descargas del usuario: {p.name}")
        if fin is not None and time.monotonic() > fin:
            log("fin: archivo estable y 8 s de margen para eventos tardíos")
            return
    log("fin por tiempo límite sin archivo estable")


def main() -> None:
    analizador = argparse.ArgumentParser()
    sub = analizador.add_subparsers(dest="comando", required=True)
    sub.add_parser("estado")
    c = sub.add_parser("controles")
    c.add_argument("--dentro", help="selector CSS o de Playwright que acota la búsqueda")
    t = sub.add_parser("clic-texto")
    t.add_argument("texto")
    t.add_argument("--exacto", action="store_true")
    t.add_argument("--indice", type=int, default=0)
    t.add_argument("--dentro", help="selector que acota la búsqueda")
    s = sub.add_parser("clic")
    s.add_argument("selector")
    s.add_argument("--nth", type=int, default=0)
    w = sub.add_parser(
        "clic-con-red", help="clic por texto y resume las respuestas JSON (sin datos)"
    )
    w.add_argument("texto")
    w.add_argument("--dentro")
    w.add_argument("--espera", type=float, default=4.0)
    w.add_argument("--abrir", help="selector a pulsar antes (p. ej. para desplegar una lista)")
    w.add_argument("--abrir-nth", type=int, default=0)
    o = sub.add_parser("posiciones")
    o.add_argument("selector")
    r = sub.add_parser("clic-rol")
    r.add_argument("rol")
    r.add_argument("nombre")
    n = sub.add_parser("contar")
    n.add_argument("tipo", choices=["texto", "rol"])
    n.add_argument("valor")
    n.add_argument("nombre", nargs="?")
    sub.add_parser("paginacion")
    sub.add_parser("conteo-tabla")
    sub.add_parser("arbol", help="nodos del árbol de departamentos (solo títulos de nodos)")
    sub.add_parser(
        "login-controles", help="pantalla de login en un contexto aislado; no escribe nada"
    )
    g = sub.add_parser(
        "vigilar-exportacion", help="registra evento de descarga, WebSocket y carpeta"
    )
    g.add_argument("--segundos", type=int, default=900)
    sub.add_parser("dialogos")
    v = sub.add_parser("ventana")
    v.add_argument("ancho", type=int)
    v.add_argument("alto", type=int)
    x = sub.add_parser("texto")
    x.add_argument("selector", help="selector de Playwright; nunca usarlo sobre tablas de datos")
    h = sub.add_parser("hover-texto")
    h.add_argument("texto")
    h.add_argument("--exacto", action="store_true")
    args = analizador.parse_args()

    with sync_playwright() as p:
        if args.comando == "login-controles":
            navegador = p.chromium.connect_over_cdp(CDP)
            aislado = navegador.new_context(ignore_https_errors=True)
            try:
                pag = aislado.new_page()
                pag.goto("https://127.0.0.1/#/", wait_until="networkidle")
                pag.wait_for_timeout(2000)
                print(json.dumps({"url": pag.url, "titulo": pag.title()}, ensure_ascii=False))
                _imprimir_controles(pag, None)
            finally:
                aislado.close()
            return
        pagina = _pagina(p)
        if args.comando == "estado":
            print(json.dumps({"url": pagina.url, "titulo": pagina.title()}, ensure_ascii=False))
        elif args.comando == "controles":
            _imprimir_controles(pagina, args.dentro)
        elif args.comando == "clic-texto":
            base = pagina.locator(args.dentro).first if args.dentro else pagina
            base.get_by_text(args.texto, exact=args.exacto).nth(args.indice).click(timeout=10_000)
            pagina.wait_for_timeout(1500)
            print(f"clic en texto {args.texto!r}; url={pagina.url}")
        elif args.comando == "clic":
            pagina.locator(args.selector).nth(args.nth).click(timeout=10_000)
            pagina.wait_for_timeout(1000)
            print(f"clic en {args.selector!r} #{args.nth}")
        elif args.comando == "clic-con-red":
            respuestas: list[object] = []
            pagina.on("response", lambda r: respuestas.append(r))
            if args.abrir:
                pagina.locator(args.abrir).nth(args.abrir_nth).click(timeout=10_000)
                pagina.wait_for_timeout(700)
            base = pagina.locator(args.dentro).first if args.dentro else pagina
            base.get_by_text(args.texto, exact=True).first.click(timeout=10_000)
            pagina.wait_for_timeout(int(args.espera * 1000))
            for resp in respuestas:
                _resumir_respuesta(resp)
        elif args.comando == "posiciones":
            loc = pagina.locator(args.selector)
            n = loc.count()
            print(f"coincidencias: {n}")
            for i in range(n):
                caja = loc.nth(i).bounding_box()
                if caja:
                    print(f"  #{i} @({round(caja['x'])},{round(caja['y'])})")
        elif args.comando == "clic-rol":
            pagina.get_by_role(args.rol, name=args.nombre).first.click()
            pagina.wait_for_timeout(1500)
            print(f"clic en rol {args.rol} {args.nombre!r}; url={pagina.url}")
        elif args.comando == "contar":
            if args.tipo == "texto":
                loc = pagina.get_by_text(args.valor)
            else:
                loc = pagina.get_by_role(args.valor, name=args.nombre)  # type: ignore[arg-type]
            print(f"coincidencias: {loc.count()}")
        elif args.comando == "paginacion":
            for t_ in pagina.locator('[class*="pagination"], [class*="pager"]').all_inner_texts():
                print(" ".join(t_.split()))
        elif args.comando == "vigilar-exportacion":
            _vigilar_exportacion(pagina, args.segundos)
        elif args.comando == "arbol":
            # Locators de Playwright: atraviesan shadow DOM (querySelectorAll no).
            anclas = pagina.locator("li[class*='level'] a[title] >> visible=true")
            for i in range(anclas.count()):
                nodo = anclas.nth(i).evaluate(
                    r"""a => {
                        const li = a.closest('li');
                        const sw = li ? li.querySelector(':scope > span[class*="switch"]') : null;
                        return {nivel: li ? (li.className.match(/level(\d+)/) || [])[1] : null,
                                titulo: a.title, clase_a: a.className,
                                switch: sw ? sw.className : '', id_li: li ? li.id : ''};
                    }"""
                )
                print(json.dumps(nodo, ensure_ascii=False))
        elif args.comando == "conteo-tabla":
            # Solo números: filas visibles, páginas y textos tipo "Total". Nunca el contenido.
            info = pagina.evaluate(
                r"""() => {
                  const vis = (el) => el.getBoundingClientRect().height > 0;
                  const cuerpos = [...document.querySelectorAll('tbody')].filter(vis);
                  const filas = cuerpos.map(b => b.querySelectorAll('tr').length);
                  const paginas = [...document.querySelectorAll('.el-pager li, [class*="pager"] li')]
                    .filter(vis).map(li => li.innerText.trim());
                  const totales = [...document.querySelectorAll('span, div, p')]
                    .filter(el => vis(el) && el.children.length === 0 && !el.closest('tbody')
                      && /total|registros en total|en total/i.test(el.innerText || ''))
                    .map(el => (el.innerText || '').trim().slice(0, 60));
                  const vacio = [...document.querySelectorAll('[class*="empty"], [class*="no-data"]')]
                    .filter(vis).map(el => (el.innerText || '').trim().slice(0, 60));
                  return {filas_por_tbody: filas, paginas, totales, vacio};
                }"""
            )
            print(json.dumps(info, ensure_ascii=False))
        elif args.comando == "ventana":
            cdp = pagina.context.new_cdp_session(pagina)
            ventana = cdp.send("Browser.getWindowForTarget")
            cdp.send(
                "Browser.setWindowBounds",
                {
                    "windowId": ventana["windowId"],
                    "bounds": {"left": 0, "top": 0, "width": args.ancho, "height": args.alto},
                },
            )
            pagina.wait_for_timeout(1000)
            print(f"ventana {args.ancho}x{args.alto}")
        elif args.comando == "texto":
            loc = pagina.locator(args.selector).first
            print(" ".join(loc.inner_text().split())[:600])
        elif args.comando == "hover-texto":
            pagina.get_by_text(args.texto, exact=args.exacto).first.hover()
            pagina.wait_for_timeout(800)
            print(f"hover en {args.texto!r}")
        elif args.comando == "dialogos":
            for t_ in pagina.locator(
                '[role="dialog"] [class*="title"], [class*="dialog"] [class*="title"], '
                '[class*="drawer"] [class*="title"], [class*="modal"] [class*="title"]'
            ).all_inner_texts():
                print(" ".join(t_.split()))


if __name__ == "__main__":
    main()
