"""Caso de uso: exportar, validar, archivar y enviar el reporte semanal de cada grupo.

No importa Playwright, smtplib, keyring, openpyxl, jinja2 ni sqlite3: solo puertos.
Un grupo que falla no detiene a los demás; un error fatal sí (y se avisa al administrador).
"""

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TypeVar

from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from asistencia_bot.domain.errores import (
    ErrorBot,
    ErrorConfiguracion,
    ErrorEntorno,
    ErrorFatal,
    ErrorGrupo,
    ErrorNoReintentable,
    ErrorNotificacion,
)
from asistencia_bot.domain.modelos import (
    ArchivoArchivado,
    Correo,
    Ejecucion,
    EstadoGrupo,
    Grupo,
    MetadatosReporte,
    Modo,
    PoliticaSinRegistros,
    ReporteExportado,
    ResultadoGrupo,
)
from asistencia_bot.domain.periodo import semana_anterior
from asistencia_bot.domain.validacion import validar_reporte
from asistencia_bot.ports import (
    Archivador,
    ExtractorAsistencia,
    InspectorReporte,
    Notificador,
    Reloj,
    RenderizadorCorreos,
    RepositorioEstado,
    VerificadorEntorno,
)

log = logging.getLogger(__name__)
T = TypeVar("T")
MAX_ADJUNTOS_RESUMEN_BYTES = 15 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PoliticaReintentos:
    intentos: int = 3
    espera_inicial_s: float = 30.0
    espera_maxima_s: float = 120.0


@dataclass(frozen=True, slots=True)
class OpcionesEjecucion:
    modo: Modo
    forzar: bool = False
    solo_grupos: tuple[str, ...] = ()


def _reintentable(error: BaseException) -> bool:
    return isinstance(error, ErrorGrupo) and not isinstance(error, ErrorNoReintentable)


class EjecutarReporteSemanal:
    def __init__(
        self,
        *,
        reloj: Reloj,
        entorno: VerificadorEntorno,
        extractor: ExtractorAsistencia,
        inspector: InspectorReporte,
        archivador: Archivador,
        notificador: Notificador | None,
        renderizador: RenderizadorCorreos,
        estado: RepositorioEstado,
        grupos: Sequence[Grupo],
        administrador: str | None,
        sin_registros: PoliticaSinRegistros,
        reintentos: PoliticaReintentos,
        version: str,
        dormir: Callable[[float], None] = time.sleep,
        nuevo_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._reloj = reloj
        self._entorno = entorno
        self._extractor = extractor
        self._inspector = inspector
        self._archivador = archivador
        self._notificador = notificador
        self._renderizador = renderizador
        self._estado = estado
        self._grupos = tuple(grupos)
        self._admin = administrador
        self._sin_registros = sin_registros
        self._reintentos = reintentos
        self._version = version
        self._dormir = dormir
        self._nuevo_id = nuevo_id

    # --- orquestación ------------------------------------------------------------------------

    def ejecutar(self, opciones: OpcionesEjecucion) -> Ejecucion:
        inicio = self._reloj.ahora()
        periodo = semana_anterior(inicio.date())
        ejecucion = Ejecucion(
            id=self._nuevo_id(),
            inicio=inicio,
            modo=opciones.modo,
            periodo=periodo,
            version_bot=self._version,
        )
        log.info(
            "inicio de ejecución",
            extra={
                "ejecucion_id": ejecucion.id,
                "modo": opciones.modo.value,
                "periodo": periodo.etiqueta(),
                "forzar": opciones.forzar,
            },
        )
        self._estado.iniciar_ejecucion(ejecucion)
        evidencias: list[Path] = []
        grupos: tuple[Grupo, ...] = ()
        try:
            grupos = self._seleccionar(opciones.solo_grupos)
            pendientes = self._omitir_ya_enviados(ejecucion, grupos, opciones)
            if pendientes:
                if problemas := self._entorno.problemas():
                    raise ErrorEntorno("; ".join(problemas))
                self._extractor.abrir()
                try:
                    for grupo in pendientes:
                        resultado = self._procesar(ejecucion, grupo)
                        self._registrar(ejecucion, resultado)
                        evidencias.extend(resultado.evidencias)
                finally:
                    self._extractor.cerrar()
        except ErrorFatal as e:
            self._marcar_fatal(ejecucion, grupos, str(e))
        except Exception as e:  # un error inesperado no debe dejar al administrador sin aviso
            log.exception("error inesperado")
            self._marcar_fatal(ejecucion, grupos, f"error inesperado: {type(e).__name__}")
        ejecucion.fin = self._reloj.ahora()
        self._enviar_resumen(ejecucion, evidencias)
        self._estado.finalizar_ejecucion(ejecucion)
        self._limpiar(ejecucion)
        log.info(
            "fin de ejecución",
            extra={
                "ejecucion_id": ejecucion.id,
                "codigo_salida": ejecucion.codigo_salida,
                "duracion_s": round(ejecucion.duracion_s, 1),
            },
        )
        return ejecucion

    def _seleccionar(self, nombres: tuple[str, ...]) -> tuple[Grupo, ...]:
        activos = tuple(g for g in self._grupos if g.activo)
        if not nombres:
            return activos
        por_nombre = {g.nombre.casefold(): g for g in activos}
        desconocidos = [n for n in nombres if n.casefold() not in por_nombre]
        if desconocidos:
            raise ErrorConfiguracion(f"grupos inexistentes o inactivos: {', '.join(desconocidos)}")
        return tuple(por_nombre[n.casefold()] for n in nombres)

    def _omitir_ya_enviados(
        self, ejecucion: Ejecucion, grupos: tuple[Grupo, ...], opciones: OpcionesEjecucion
    ) -> list[Grupo]:
        pendientes: list[Grupo] = []
        for grupo in grupos:
            if (
                opciones.modo is Modo.PRODUCCION
                and not opciones.forzar
                and self._estado.ya_enviado(ejecucion.periodo, grupo.nombre)
            ):
                self._registrar(
                    ejecucion, ResultadoGrupo(grupo.nombre, EstadoGrupo.OMITIDO_YA_ENVIADO)
                )
            else:
                pendientes.append(grupo)
        return pendientes

    def _marcar_fatal(self, ejecucion: Ejecucion, grupos: tuple[Grupo, ...], error: str) -> None:
        log.error("error fatal", extra={"ejecucion_id": ejecucion.id, "error": error})
        ejecucion.error_fatal = error
        procesados = {r.grupo for r in ejecucion.resultados}
        for grupo in grupos:
            if grupo.nombre not in procesados:
                self._registrar(
                    ejecucion,
                    ResultadoGrupo(grupo.nombre, EstadoGrupo.FALLIDO, error="no se procesó"),
                )

    def _registrar(self, ejecucion: Ejecucion, resultado: ResultadoGrupo) -> None:
        ejecucion.resultados.append(resultado)
        self._estado.registrar_resultado(ejecucion, resultado)
        log.info(
            "resultado de grupo",
            extra={
                "ejecucion_id": ejecucion.id,
                "grupo": resultado.grupo,
                "estado": resultado.estado.value,
                "filas": resultado.filas,
                "intentos": resultado.intentos,
                "error": resultado.error,
            },
        )

    # --- un grupo ---------------------------------------------------------------------------

    def _con_reintentos(self, funcion: Callable[[], T]) -> T:
        reintentador = Retrying(
            stop=stop_after_attempt(self._reintentos.intentos),
            wait=wait_exponential(
                multiplier=self._reintentos.espera_inicial_s, max=self._reintentos.espera_maxima_s
            ),
            retry=retry_if_exception(_reintentable),
            sleep=self._dormir,
            reraise=True,
            before_sleep=lambda estado: log.warning(
                "reintento de grupo",
                extra={
                    "intento": estado.attempt_number,
                    "error": str(estado.outcome.exception()) if estado.outcome else None,
                },
            ),
        )
        return reintentador(funcion)

    def _procesar(self, ejecucion: Ejecucion, grupo: Grupo) -> ResultadoGrupo:
        inicio = time.monotonic()
        intentos = 0

        def intento() -> tuple[ReporteExportado, MetadatosReporte]:
            nonlocal intentos
            intentos += 1
            reporte = self._extractor.exportar(grupo, ejecucion.periodo)
            return reporte, self._inspector.leer_metadatos(reporte.ruta)

        def resultado(estado: EstadoGrupo, **campos: object) -> ResultadoGrupo:
            base = ResultadoGrupo(
                grupo.nombre,
                estado,
                intentos=intentos,
                duracion_s=round(time.monotonic() - inicio, 1),
            )
            return replace(base, **campos)  # type: ignore[arg-type]

        try:
            reporte, meta = self._con_reintentos(intento)
        except ErrorGrupo as e:
            evidencias: tuple[Path, ...] = ()
            try:
                evidencias = self._extractor.guardar_evidencia(f"{ejecucion.id[:8]}_{grupo.slug}")
            except Exception:
                log.warning("no se pudo guardar evidencia", extra={"grupo": grupo.nombre})
            return resultado(EstadoGrupo.FALLIDO, error=str(e), evidencias=evidencias)

        consulta = reporte.consulta
        validacion = validar_reporte(meta, ejecucion.periodo, grupo, consulta)
        comunes: dict[str, object] = {
            "filas": meta.filas,
            "registros_consulta": consulta.registros if consulta else None,
            "advertencias": validacion.advertencias,
        }
        if not validacion.valido:
            return resultado(EstadoGrupo.FALLIDO, error="; ".join(validacion.errores), **comunes)

        try:
            archivo = self._archivador.archivar(reporte.ruta, ejecucion.periodo, grupo)
        except ErrorGrupo as e:
            return resultado(EstadoGrupo.FALLIDO, error=str(e), **comunes)
        comunes |= {"archivo": archivo.ruta.name, "sha256": archivo.sha256}

        if ejecucion.modo is Modo.DRY_RUN:
            estado = (
                EstadoGrupo.OMITIDO_SIN_REGISTROS
                if meta.filas == 0
                else EstadoGrupo.VALIDADO_SIN_ENVIO
            )
            return resultado(estado, **comunes)

        if meta.filas == 0 and self._sin_registros is PoliticaSinRegistros.OMITIR_Y_REPORTAR:
            return resultado(EstadoGrupo.OMITIDO_SIN_REGISTROS, **comunes)

        correo = (
            self._renderizador.correo_sin_registros(grupo, ejecucion.periodo)
            if meta.filas == 0
            else self._renderizador.correo_jefe(
                grupo, ejecucion.periodo, archivo, self._nombre_adjunto(archivo)
            )
        )
        try:
            destinatarios = self._enviar(correo, ejecucion.modo)
        except ErrorNotificacion as e:
            return resultado(EstadoGrupo.FALLIDO, error=f"no se envió: {e}", **comunes)
        return resultado(EstadoGrupo.ENVIADO, destinatarios=destinatarios, **comunes)

    @staticmethod
    def _nombre_adjunto(archivo: ArchivoArchivado) -> str:
        return archivo.ruta.name

    def _enviar(self, correo: Correo, modo: Modo) -> tuple[str, ...]:
        if self._notificador is None:
            raise ErrorConfiguracion("no hay notificador configurado (falta [smtp])")
        if modo is Modo.PRUEBA:
            if not self._admin:
                raise ErrorConfiguracion("el modo prueba requiere el correo del administrador")
            correo = self._renderizador.redirigir_a_prueba(correo, self._admin)
        elif not correo.para:
            raise ErrorNotificacion("el grupo no tiene jefe configurado")
        self._notificador.enviar(correo)
        return (*correo.para, *correo.cc)

    # --- cierre -------------------------------------------------------------------------------

    def _enviar_resumen(self, ejecucion: Ejecucion, evidencias: list[Path]) -> None:
        if not ejecucion.modo.envia_correos:
            return
        if self._notificador is None or not self._admin:
            ejecucion.error_resumen = "no hay SMTP o administrador configurado para el resumen"
            return
        adjuntos: list[Path] = []
        total = 0
        for ruta in evidencias:
            tamano = ruta.stat().st_size if ruta.exists() else 0
            if tamano and total + tamano <= MAX_ADJUNTOS_RESUMEN_BYTES:
                adjuntos.append(ruta)
                total += tamano
        try:
            correo = self._renderizador.correo_resumen(ejecucion, self._admin, adjuntos)
            self._notificador.enviar(correo)
        except ErrorBot as e:
            ejecucion.error_resumen = f"no se pudo enviar el resumen: {e}"
            log.error("resumen no enviado", extra={"ejecucion_id": ejecucion.id, "error": str(e)})

    def _limpiar(self, ejecucion: Ejecucion) -> None:
        try:
            borrados = self._archivador.limpiar(ejecucion.fin or self._reloj.ahora())
            if borrados:
                log.info("retención aplicada", extra={"archivos_borrados": borrados})
        except OSError as e:
            log.warning("no se pudo aplicar la retención", extra={"error": type(e).__name__})
