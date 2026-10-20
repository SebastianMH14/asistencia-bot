"""Implementa `ExtractorAsistencia` automatizando la interfaz web de HikCentral."""

import contextlib
import logging
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from asistencia_bot.adapters.descargas import VigilanteDescargas
from asistencia_bot.adapters.hikcentral import selectores as s
from asistencia_bot.adapters.hikcentral.paginas import MenuUsuario, PaginaLogin, PaginaRegistros
from asistencia_bot.adapters.hikcentral.sesion import SesionNavegador, resumir_error
from asistencia_bot.domain.errores import (
    ErrorBot,
    ErrorCredenciales,
    ErrorExtraccion,
    ErrorNoReintentable,
    ErrorPeriodoNoCoincide,
)
from asistencia_bot.domain.modelos import Grupo, Periodo, ReporteExportado
from asistencia_bot.ports import AlmacenCredenciales

log = logging.getLogger(__name__)


class ExtractorHikCentralUI:
    def __init__(
        self,
        *,
        sesion: SesionNavegador,
        vigilante: VigilanteDescargas,
        credenciales: AlmacenCredenciales,
        usuario: str,
        timeout_captura_s: float,
        relogins_maximos: int = 1,
    ) -> None:
        self._sesion = sesion
        self._vigilante = vigilante
        self._credenciales = credenciales
        self._usuario = usuario
        self._timeout_captura = timeout_captura_s
        self._relogins_maximos = relogins_maximos
        self._relogins = 0

    def _clave(self) -> str:
        clave = self._credenciales.obtener("hikcentral", self._usuario)
        if not clave:
            raise ErrorCredenciales(
                f"no hay contraseña de HikCentral para {self._usuario!r}; use "
                f"'asistencia-bot credenciales configurar hikcentral -u {self._usuario}'"
            )
        return clave

    def _login(self) -> None:
        PaginaLogin(self._sesion.page, self._sesion.timeout_ms).iniciar_sesion(
            self._usuario, self._clave()
        )
        log.info("sesión de HikCentral iniciada")

    def abrir(self) -> None:
        self._sesion.abrir()
        try:
            self._login()
        except PlaywrightError as e:
            self._sesion.cerrar()
            raise ErrorExtraccion(f"no se pudo iniciar sesión: {resumir_error(e)}") from None
        except ErrorBot:
            self._sesion.cerrar()
            raise

    def _asegurar_sesion(self) -> None:
        """Recarga la página; si la sesión expiró, vuelve a iniciarla (una vez por ejecución)."""
        self._sesion.recargar()
        page = self._sesion.page
        # Espera a que la página "aterrice": menú del módulo, login o aviso de sesión vencida.
        with contextlib.suppress(PlaywrightError):
            s.pestana_modulo(page).or_(s.boton_login_visible(page).first).or_(
                s.notificacion_sesion_expirada(page).first
            ).first.wait_for(timeout=self._sesion.timeout_ms)
        expirada = (
            PaginaLogin(page, self._sesion.timeout_ms).visible()
            or s.notificacion_sesion_expirada(page).count() > 0
        )
        if not expirada:
            return
        if self._relogins >= self._relogins_maximos:
            raise ErrorExtraccion("la sesión de HikCentral expiró de nuevo")
        self._relogins += 1
        log.warning("la sesión de HikCentral expiró; se vuelve a iniciar")
        if not PaginaLogin(page, self._sesion.timeout_ms).visible():
            page.goto(self._sesion.url, wait_until="domcontentloaded")
        self._login()

    def exportar(self, grupo: Grupo, periodo: Periodo) -> ReporteExportado:
        if periodo.desde.weekday() != 0 or (periodo.hasta - periodo.desde).days != 6:
            raise ErrorNoReintentable(
                "solo se soporta la semana anterior (lunes a domingo); el rango personalizado "
                "no está implementado"
            )
        etapa = "preparar la página"
        inicio = time.monotonic()
        try:
            self._asegurar_sesion()
            self._sesion.iniciar_tramo()
            registros = PaginaRegistros(self._sesion.page, self._sesion.timeout_ms)
            etapa = "abrir el reporte"
            registros.abrir()
            etapa = "elegir el periodo"
            registros.elegir_periodo(s.PERIODO_SEMANA_ANTERIOR)
            etapa = "seleccionar el grupo"
            personas, primera = registros.seleccionar_grupo(grupo.departamento_hik)
            etapa = "recorrer la consulta"
            consulta = registros.recorrer_consulta(primera)
            log.info(
                "consulta de la interfaz",
                extra={
                    "grupo": grupo.nombre,
                    "personas": personas,
                    "registros": consulta.registros,
                    "paginas": consulta.paginas,
                },
            )
            if consulta.periodo_consultado != periodo:
                raise ErrorPeriodoNoCoincide(
                    f"HikCentral consultó {consulta.periodo_consultado.texto_hik()} y se "
                    f"esperaba {periodo.texto_hik()}"
                )
            # Desde aquí se escribe la contraseña de confirmación: sin trace.
            self._sesion.pausar_tramo()
            etapa = "exportar"
            antes = self._vigilante.instantanea()
            registros.abrir_exportacion().exportar(self._clave())
            etapa = "capturar el archivo"
            ruta = self._vigilante.esperar(
                antes, periodo.nombre_archivo_hik(), self._timeout_captura
            )
        except PlaywrightError as e:
            raise ErrorExtraccion(f"{etapa}: {resumir_error(e)}") from None
        log.info(
            "archivo capturado",
            extra={
                "grupo": grupo.nombre,
                "archivo": ruta.name,
                "duracion_s": round(time.monotonic() - inicio, 1),
            },
        )
        self._sesion.grupo_terminado()
        return ReporteExportado(grupo.nombre, ruta, ruta.stat().st_size, consulta)

    def guardar_evidencia(self, etiqueta: str) -> tuple[Path, ...]:
        return self._sesion.guardar_evidencia(etiqueta)

    def cerrar(self) -> None:
        with contextlib.suppress(Exception):
            if (
                self._sesion.page
                and not PaginaLogin(self._sesion.page, self._sesion.timeout_ms).visible()
            ):
                MenuUsuario(self._sesion.page, self._sesion.timeout_ms).cerrar_sesion(self._usuario)
                log.info("sesión de HikCentral cerrada")
        self._sesion.cerrar()
