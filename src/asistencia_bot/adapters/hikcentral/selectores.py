"""TODOS los selectores de HikCentral AC 2.4 en un solo lugar.

Origen y trampas de cada uno: DISCOVERY.md §7.1. Reglas aprendidas en la Fase 1:
- Textos de la interfaz en español y exactos; nada de XPath frágil ni clases autogeneradas.
- Siempre filtrar por visibles: la SPA conserva páginas ocultas con controles duplicados.
- No usar get_by_role(name=...) para la pestaña del módulo ni para el panel de exportación.
"""

import json
import re

from playwright.sync_api import Locator, Page

API_REGISTROS = "/ISAPI/Bumblebee/AttendancePlugin/V1/Record"
REPORTE = "Registros de entradas y salidas"
SUBMENU_REGISTRO = "Registro de asistencia"
MODULO_ASISTENCIA = "Asistencia"
PERIODO_SEMANA_ANTERIOR = "Última semana"
OPCIONES_PERIODO = (
    "Hoy",
    "Ayer",
    "Semana actual",
    "Última semana",
    "Mes actual",
    "Mes anterior",
    "Últimos 3 meses",
    "Últimos 6 meses",
    "Este año",
    "Personalizado",
)
TITULO_DIALOGO_EXPORTAR = "Configuración a exportar"
MODO_PREDEFINIDO = "Predefinido"


def _css_str(valor: str) -> str:
    """Cadena CSS entre comillas dobles con escapes (para atributos con tildes o puntos)."""
    return json.dumps(valor, ensure_ascii=False)


# --- Login -------------------------------------------------------------------------------


def pestana_administracion(page: Page) -> Locator:
    return page.get_by_role("tab", name="Administración", exact=True)


def campo_usuario(page: Page) -> Locator:
    """Trae readonly hasta recibir el foco: hacer clic antes de fill."""
    return page.get_by_placeholder("Nombre de usuario")


def campo_clave_login(page: Page) -> Locator:
    return page.get_by_placeholder("Contraseña").filter(visible=True).first


def boton_iniciar_sesion(page: Page) -> Locator:
    return page.get_by_role("button", name="Iniciar sesión", exact=True)


def boton_login_visible(page: Page) -> Locator:
    return page.locator("button.login-btn").filter(visible=True)


def notificacion_sesion_expirada(page: Page) -> Locator:
    """ "Inicie sesión de nuevo." — intercepta los clics mientras está visible."""
    return page.locator(".session-expire-notification").filter(visible=True)


def mensajes_error(page: Page) -> Locator:
    return page.locator(
        ".el-message--error, .el-form-item__error, .el-message-box__message"
    ).filter(visible=True)


# --- Navegación --------------------------------------------------------------------------


def pestana_modulo(page: Page, nombre: str = MODULO_ASISTENCIA) -> Locator:
    """Pestaña del menú superior por su texto exacto (activa o no, sin "Revisión de …")."""
    return (
        page.locator("[role='tab'].el-tabs__item")
        .filter(has=page.get_by_text(nombre, exact=True))
        .filter(visible=True)
        .first
    )


def aviso_actualizar_ok(page: Page) -> Locator:
    """OK del aviso "Haga clic aquí para actualizar…". Nunca marcar "No vuelva a mostrar"."""
    return page.locator("button.refresh-know").filter(visible=True)


def item_menu(page: Page, texto: str) -> Locator:
    """El <li> trae un tooltip oculto en su textContent: se busca el nodo de texto exacto."""
    return page.locator("ul.el-menu").get_by_text(texto, exact=True).filter(visible=True)


def boton_exportar(page: Page) -> Locator:
    return page.locator("button.export-btn").filter(visible=True).first


# --- Periodo -----------------------------------------------------------------------------


def desplegables(page: Page) -> Locator:
    """Periodo y tamaño de página comparten placeholder; se distinguen por su valor."""
    return page.get_by_placeholder("Por favor, seleccione.").filter(visible=True)


def opcion_desplegable(page: Page, texto: str) -> Locator:
    return (
        page.locator(".el-select-dropdown")
        .filter(visible=True)
        .get_by_text(texto, exact=True)
        .first
    )


# --- Personas ----------------------------------------------------------------------------


def boton_personas(page: Page) -> Locator:
    return (
        page.locator("button")
        .filter(has_text=re.compile(r"personas seleccionadas\s*$", re.I))
        .filter(visible=True)
        .first
    )


PATRON_PERSONAS = re.compile(r"(\d+)\s+personas seleccionadas", re.I)


def nodo_departamento(page: Page, departamento: str) -> Locator:
    """Nodo del árbol zTree; sus id son UUID que cambian, se usa el title."""
    return (
        page.locator(f"li[class*='level'] a[title={_css_str(departamento)}]")
        .filter(visible=True)
        .first
    )


def casilla_seleccionar_todos(page: Page) -> Locator:
    return (
        page.locator("label.el-checkbox")
        .filter(has_text="Seleccionar todos")
        .filter(visible=True)
        .first
    )


def boton_aceptar(page: Page) -> Locator:
    return page.locator("button[title='Aceptar']").filter(visible=True).first


# --- Paginación de la tabla --------------------------------------------------------------


def boton_pagina_siguiente(page: Page) -> Locator:
    return page.locator("button.btn-next").filter(visible=True).first


def boton_pagina_anterior(page: Page) -> Locator:
    return page.locator("button.btn-prev").filter(visible=True).first


# --- Exportar ----------------------------------------------------------------------------


def dialogo_exportar(page: Page) -> Locator:
    """Por aria-label: aria-labelledby apunta a un id repetido y get_by_role no lo encuentra."""
    return (
        page.locator(f"[role='dialog'][aria-label={_css_str(TITULO_DIALOGO_EXPORTAR)}]")
        .filter(visible=True)
        .first
    )


def radio_excel(dialogo: Locator) -> Locator:
    return dialogo.locator("label[title='Excel']").filter(visible=True).first


def campo_modo_monitor(dialogo: Locator) -> Locator:
    return dialogo.get_by_placeholder(MODO_PREDEFINIDO).filter(visible=True).first


def campo_clave_exportar(dialogo: Locator) -> Locator:
    return dialogo.get_by_placeholder("Contraseña").filter(visible=True).first


def boton_confirmar_exportar(dialogo: Locator) -> Locator:
    return dialogo.locator("button[title='Exportar']").filter(visible=True).first


# --- Usuario -----------------------------------------------------------------------------


def menu_usuario(page: Page, usuario: str) -> Locator:
    return page.locator(f"div[role='button'][title={_css_str(usuario)}]").filter(visible=True).first


def opcion_cerrar_sesion(page: Page) -> Locator:
    return (
        page.locator(".el-dropdown-menu")
        .filter(visible=True)
        .get_by_text("Cerrar sesión", exact=True)
        .first
    )


def boton_confirmar_mensaje(page: Page) -> Locator:
    return page.locator(".el-message-box .el-button--primary").filter(visible=True)
