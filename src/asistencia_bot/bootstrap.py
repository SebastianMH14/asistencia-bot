"""Composition root: el único lugar que elige e instancia adaptadores concretos."""

from asistencia_bot import __version__
from asistencia_bot.adapters.archivador import ArchivadorLocal, ReglaRetencion
from asistencia_bot.adapters.correo_smtp import NotificadorSmtp
from asistencia_bot.adapters.credenciales_keyring import AlmacenKeyring
from asistencia_bot.adapters.descargas import VigilanteDescargas
from asistencia_bot.adapters.entorno import VerificadorEntornoLocal
from asistencia_bot.adapters.estado_sqlite import EstadoSqlite
from asistencia_bot.adapters.excel_validador import InspectorExcel
from asistencia_bot.adapters.hikcentral.extractor_ui import ExtractorHikCentralUI
from asistencia_bot.adapters.hikcentral.sesion import SesionNavegador
from asistencia_bot.adapters.logs import PATRON_LOGS_ROTADOS
from asistencia_bot.adapters.plantillas import RenderizadorJinja
from asistencia_bot.adapters.reloj import RelojSistema
from asistencia_bot.config import Ajustes, Configuracion
from asistencia_bot.domain.modelos import REPORTE_HIK, Modo
from asistencia_bot.ports import AlmacenCredenciales
from asistencia_bot.services.ejecutar_reporte_semanal import (
    EjecutarReporteSemanal,
    PoliticaReintentos,
)


def crear_almacen_credenciales() -> AlmacenCredenciales:
    return AlmacenKeyring()


def crear_renderizador() -> RenderizadorJinja:
    return RenderizadorJinja(__version__)


def crear_estado(ajustes: Ajustes) -> EstadoSqlite:
    return EstadoSqlite(ajustes.rutas.estado_db)


def crear_notificador(
    ajustes: Ajustes, credenciales: AlmacenCredenciales
) -> NotificadorSmtp | None:
    smtp = ajustes.smtp
    if smtp is None:
        return None
    return NotificadorSmtp(
        host=smtp.host,
        puerto=smtp.puerto,
        usuario=smtp.usuario,
        remitente=smtp.remitente,
        starttls=smtp.starttls,
        timeout_s=smtp.timeout_s,
        reintentos=smtp.reintentos,
        credenciales=credenciales,
    )


def crear_verificador(
    ajustes: Ajustes, credenciales: AlmacenCredenciales, modo: Modo
) -> VerificadorEntornoLocal:
    hik = ajustes.hikcentral
    return VerificadorEntornoLocal(
        url_hikcentral=hik.url,
        host_hikcentral=hik.host,
        usuario_hikcentral=hik.usuario,
        carpeta_descargas=hik.carpeta_descargas,
        puerto_hcwebcontrol=hik.puerto_hcwebcontrol,
        credenciales=credenciales,
        usuario_smtp=ajustes.smtp.usuario if ajustes.smtp and modo.envia_correos else None,
    )


def construir_servicio(
    config: Configuracion, modo: Modo, *, visible: bool = False
) -> EjecutarReporteSemanal:
    a = config.ajustes
    credenciales = crear_almacen_credenciales()
    sesion = SesionNavegador(
        url=a.hikcentral.url,
        navegador=a.hikcentral.navegador,
        headless=a.hikcentral.headless and not visible,
        timeout_ui_s=a.hikcentral.timeout_ui_s,
        carpeta_capturas=a.rutas.capturas,
        carpeta_traces=a.rutas.traces,
        trace_en_error=a.hikcentral.trace_en_error,
    )
    extractor = ExtractorHikCentralUI(
        sesion=sesion,
        vigilante=VigilanteDescargas(a.hikcentral.carpeta_descargas, REPORTE_HIK),
        credenciales=credenciales,
        usuario=a.hikcentral.usuario,
        timeout_captura_s=a.hikcentral.timeout_captura_s,
    )
    archivador = ArchivadorLocal(
        a.rutas.salida,
        [
            ReglaRetencion(a.rutas.salida, "*/Asistencia_*.xlsx", a.retencion.excel_dias),
            ReglaRetencion(a.rutas.capturas, "*.png", a.retencion.evidencias_dias),
            ReglaRetencion(a.rutas.traces, "*.zip", a.retencion.evidencias_dias),
            ReglaRetencion(a.rutas.logs, PATRON_LOGS_ROTADOS, a.retencion.logs_dias),
        ],
    )
    return EjecutarReporteSemanal(
        reloj=RelojSistema(a.ejecucion.zona_horaria),
        entorno=crear_verificador(a, credenciales, modo),
        extractor=extractor,
        inspector=InspectorExcel(),
        archivador=archivador,
        notificador=crear_notificador(a, credenciales),
        renderizador=crear_renderizador(),
        estado=crear_estado(a),
        grupos=config.grupos_activos,
        administrador=a.administrador.correo if a.administrador else None,
        sin_registros=a.ejecucion.sin_registros,
        reintentos=PoliticaReintentos(
            intentos=a.ejecucion.reintentos,
            espera_inicial_s=a.ejecucion.espera_inicial_s,
            espera_maxima_s=a.ejecucion.espera_maxima_s,
        ),
        version=__version__,
    )
