"""Page Objects de HikCentral AC 2.4. Usan solo los selectores de `selectores.py`."""

import json
import logging
from datetime import date
from typing import Any

from playwright.sync_api import Locator, Page, Response
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from asistencia_bot.adapters.hikcentral import selectores as s
from asistencia_bot.domain.errores import ErrorExtraccion, ErrorLogin
from asistencia_bot.domain.modelos import ClaveRegistro, ConsultaInterfaz, Periodo

log = logging.getLogger(__name__)
MAX_PAGINAS = 200


def _es_consulta(respuesta: Response) -> bool:
    return s.API_REGISTROS in respuesta.url and respuesta.request.method == "POST"


class PaginaLogin:
    def __init__(self, page: Page, timeout_ms: float) -> None:
        self._page = page
        self._timeout = timeout_ms

    def visible(self) -> bool:
        return s.boton_login_visible(self._page).count() > 0

    def iniciar_sesion(self, usuario: str, clave: str) -> None:
        page = self._page
        s.campo_usuario(page).wait_for(timeout=self._timeout)
        s.pestana_administracion(page).click()
        campo = s.campo_usuario(page)
        campo.click()  # quita el readonly anti-autocompletado
        campo.fill(usuario)
        campo_clave = s.campo_clave_login(page)
        campo_clave.click()
        campo_clave.fill(clave)
        s.boton_iniciar_sesion(page).click()
        try:
            s.pestana_modulo(page).wait_for(timeout=self._timeout * 1.5)
        except PlaywrightTimeoutError:
            mensajes = [" ".join(t.split())[:120] for t in s.mensajes_error(page).all_inner_texts()]
            raise ErrorLogin(
                f"HikCentral no completó el inicio de sesión de {usuario!r}"
                + (f": {'; '.join(mensajes)}" if mensajes else "")
            ) from None


class DialogoExportar:
    def __init__(self, page: Page, dialogo: Locator) -> None:
        self._page = page
        self._dialogo = dialogo

    def exportar(self, clave: str) -> None:
        excel = s.radio_excel(self._dialogo)
        if "is-checked" not in (excel.get_attribute("class") or ""):
            excel.click()
        modo = s.campo_modo_monitor(self._dialogo).input_value()
        if modo != s.MODO_PREDEFINIDO:
            raise ErrorExtraccion(f"el modo monitor es {modo!r} y se esperaba Predefinido")
        campo = s.campo_clave_exportar(self._dialogo)
        campo.click()
        campo.fill(clave)
        s.boton_confirmar_exportar(self._dialogo).click()
        self._page.wait_for_timeout(1500)
        errores = [
            " ".join(t.split())[:120] for t in s.mensajes_error(self._page).all_inner_texts()
        ]
        if errores:
            raise ErrorExtraccion(f"la interfaz mostró un error al exportar: {'; '.join(errores)}")


class PaginaRegistros:
    def __init__(self, page: Page, timeout_ms: float) -> None:
        self._page = page
        self._timeout = timeout_ms

    def cerrar_aviso(self) -> None:
        ok = s.aviso_actualizar_ok(self._page)
        if ok.count():
            ok.first.click()

    def abrir(self) -> None:
        page = self._page
        s.pestana_modulo(page).click()
        page.wait_for_timeout(1000)
        self.cerrar_aviso()
        item = s.item_menu(page, s.REPORTE)
        if not item.count():
            s.item_menu(page, s.SUBMENU_REGISTRO).first.click()
        item.first.click()
        s.boton_exportar(page).wait_for(timeout=self._timeout)
        self.cerrar_aviso()

    def elegir_periodo(self, opcion: str) -> None:
        candidatos = s.desplegables(self._page)
        valores = [candidatos.nth(i).input_value() for i in range(candidatos.count())]
        indice = next((i for i, v in enumerate(valores) if v in s.OPCIONES_PERIODO), None)
        if indice is None:
            raise ErrorExtraccion("no se encontró el selector de periodo")
        candidatos.nth(indice).click()
        s.opcion_desplegable(self._page, opcion).click()
        self._page.wait_for_timeout(800)
        elegido = candidatos.nth(indice).input_value()
        if elegido != opcion:
            raise ErrorExtraccion(f"el periodo quedó en {elegido!r} y no en {opcion!r}")

    def seleccionar_grupo(self, departamento: str) -> tuple[int | None, Response]:
        page = self._page
        s.boton_personas(page).click()
        s.nodo_departamento(page, departamento).click()
        page.wait_for_timeout(800)
        todos = s.casilla_seleccionar_todos(page)
        if "is-checked" not in (todos.get_attribute("class") or ""):
            todos.click()
        with page.expect_response(_es_consulta, timeout=self._timeout) as info:
            s.boton_aceptar(page).click()
        coincidencia = s.PATRON_PERSONAS.search(s.boton_personas(page).inner_text())
        personas = int(coincidencia.group(1)) if coincidencia else None
        return personas, info.value

    def recorrer_consulta(self, primera: Response) -> ConsultaInterfaz:
        """Suma páginas y junta (EmployeeID, Date) en memoria. Ver ADR-0005: la suma puede
        quedarse corta con más de dos páginas; el Excel es la fuente completa."""
        periodo = _periodo_consultado(primera)
        claves: set[ClaveRegistro] = set()
        registros = paginas = 0
        respuesta = primera
        while True:
            datos = _datos(respuesta)
            lote: list[dict[str, Any]] = datos.get("OnOffDutyRecord") or []
            registros += len(lote)
            paginas += 1
            claves.update(c for c in (_clave(r) for r in lote) if c is not None)
            if datos.get("NextPage") != 1 or paginas >= MAX_PAGINAS:
                break
            with self._page.expect_response(_es_consulta, timeout=self._timeout) as info:
                s.boton_pagina_siguiente(self._page).click()
            respuesta = info.value
        for _ in range(paginas - 1):
            s.boton_pagina_anterior(self._page).click()
            self._page.wait_for_timeout(500)
        return ConsultaInterfaz(paginas, registros, periodo, frozenset(claves))

    def abrir_exportacion(self) -> DialogoExportar:
        s.boton_exportar(self._page).click()
        dialogo = s.dialogo_exportar(self._page)
        dialogo.wait_for(timeout=self._timeout)
        return DialogoExportar(self._page, dialogo)


class MenuUsuario:
    def __init__(self, page: Page, timeout_ms: float) -> None:
        self._page = page
        self._timeout = timeout_ms

    def cerrar_sesion(self, usuario: str) -> None:
        s.menu_usuario(self._page, usuario).hover()
        s.opcion_cerrar_sesion(self._page).click(timeout=5_000)
        confirmar = s.boton_confirmar_mensaje(self._page)
        if confirmar.count():
            confirmar.first.click()
        s.campo_usuario(self._page).wait_for(timeout=self._timeout)


def _datos(respuesta: Response) -> dict[str, Any]:
    cuerpo: Any = respuesta.json()
    estado = cuerpo.get("ResponseStatus", {}) if isinstance(cuerpo, dict) else {}
    if estado.get("ErrorCode", 0) != 0:
        raise ErrorExtraccion(
            f"la consulta de la tabla devolvió ErrorCode={estado.get('ErrorCode')}"
        )
    datos = estado.get("Data")
    if not isinstance(datos, dict):
        raise ErrorExtraccion("la consulta de la tabla no trajo datos")
    return datos


def _periodo_consultado(respuesta: Response) -> Periodo:
    try:
        consulta = json.loads(respuesta.request.post_data or "{}")["RecordRequest"]["QueryInfo"]
        return Periodo(
            date.fromisoformat(consulta["BeginTime"][:10]),
            date.fromisoformat(consulta["EndTime"][:10]),
        )
    except (KeyError, TypeError, ValueError):
        raise ErrorExtraccion("no se pudo leer el rango de la consulta de la tabla") from None


def _clave(registro: dict[str, Any]) -> ClaveRegistro | None:
    try:
        base = registro["BaseInfo"]
        return (
            str(base["PersonInfo"]["EmployeeID"]).strip(),
            date.fromisoformat(base["Date"][:10]),
        )
    except (KeyError, TypeError, ValueError):
        return None
