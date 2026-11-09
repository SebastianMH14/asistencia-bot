"""Revisión diaria: ¿hoy le han llegado marcaciones a HikCentral (ADR-0006)? ¿Salió el reporte de
la semana anterior (ADR-0008)? Si algo falla, avisa al administrador.

No importa smtplib, jinja2, sqlite3 ni el formato del log de HikCentral: solo puertos.
"""

import logging
from dataclasses import dataclass, replace
from datetime import datetime, time

from asistencia_bot.domain.errores import ErrorBot, ErrorLectura
from asistencia_bot.domain.vigilancia import (
    EstadoLector,
    EstadoReporte,
    revisar_lector,
    revisar_reporte,
)
from asistencia_bot.ports import (
    FuenteEventos,
    Notificador,
    Reloj,
    RenderizadorCorreos,
    RepositorioEstado,
)

log = logging.getLogger(__name__)

# Las ejecuciones de una semana son unas pocas; 50 cubren de sobra las pruebas manuales.
EJECUCIONES_A_REVISAR = 50


@dataclass(frozen=True, slots=True)
class ResultadoVigilancia:
    estado: EstadoLector | None
    error: str | None = None  # no se pudo revisar el lector
    reporte: EstadoReporte | None = None  # None: antes del plazo del lunes o sin producción
    error_reporte: str | None = None  # no se pudo leer el historial de ejecuciones
    alerta_enviada: bool = False  # la del lector
    alerta_reporte_enviada: bool = False
    error_envio: str | None = None

    @property
    def problema_lector(self) -> bool:
        return self.error is not None or (self.estado is not None and self.estado.sin_marcaciones)

    @property
    def reporte_pendiente(self) -> bool:
        return self.reporte is not None and self.reporte.pendiente

    @property
    def hay_problema(self) -> bool:
        return self.problema_lector or self.reporte_pendiente or self.error_reporte is not None

    @property
    def codigo_salida(self) -> int:
        """0 todo bien, 1 hay un problema o no se pudo revisar, 2 había que avisar y no se pudo."""
        if self.error_envio:
            return 2
        return 1 if self.hay_problema else 0


class VigilarLector:
    def __init__(
        self,
        *,
        reloj: Reloj,
        fuente: FuenteEventos,
        notificador: Notificador | None,
        renderizador: RenderizadorCorreos,
        administrador: str | None,
        estado: RepositorioEstado | None = None,
        plazo_reporte: time | None = None,  # None: no se revisa el reporte semanal
    ) -> None:
        self._reloj = reloj
        self._fuente = fuente
        self._notificador = notificador
        self._renderizador = renderizador
        self._admin = administrador
        self._estado = estado
        self._plazo_reporte = plazo_reporte

    def ejecutar(self, *, avisar: bool = True) -> ResultadoVigilancia:
        ahora = self._reloj.ahora()
        resultado = self._revisar_reporte(self._revisar_lector(ahora), ahora)
        if not avisar or not (resultado.problema_lector or resultado.reporte_pendiente):
            return resultado
        if self._notificador is None or not self._admin:
            return replace(resultado, error_envio="no hay SMTP o administrador configurado")
        if resultado.problema_lector:
            try:
                self._notificador.enviar(
                    self._renderizador.correo_alerta_lector(
                        self._admin, ahora, resultado.estado, resultado.error
                    )
                )
                resultado = replace(resultado, alerta_enviada=True)
            except ErrorBot as e:
                log.error("alerta del lector no enviada", extra={"error": str(e)})
                resultado = replace(resultado, error_envio=str(e))
        if resultado.reporte is not None and resultado.reporte.pendiente:
            try:
                self._notificador.enviar(
                    self._renderizador.correo_alerta_reporte(self._admin, ahora, resultado.reporte)
                )
                resultado = replace(resultado, alerta_reporte_enviada=True)
            except ErrorBot as e:
                log.error("alerta del reporte semanal no enviada", extra={"error": str(e)})
                resultado = replace(resultado, error_envio=str(e))
        return resultado

    def _revisar_lector(self, ahora: datetime) -> ResultadoVigilancia:
        desde = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            resultado = ResultadoVigilancia(revisar_lector(self._fuente.muestras(), desde))
        except ErrorLectura as e:
            resultado = ResultadoVigilancia(None, error=str(e))
        estado = resultado.estado
        log.log(
            logging.WARNING if resultado.problema_lector else logging.INFO,
            "vigilancia del lector",
            extra={
                "desde": desde.isoformat(),
                "eventos": estado.eventos if estado else None,
                "ultimo_evento": (
                    estado.ultimo_evento.isoformat() if estado and estado.ultimo_evento else None
                ),
                "error": resultado.error,
            },
        )
        return resultado

    def _revisar_reporte(
        self, resultado: ResultadoVigilancia, ahora: datetime
    ) -> ResultadoVigilancia:
        if self._estado is None or self._plazo_reporte is None:
            return resultado
        try:
            ejecuciones = self._estado.ultimas_ejecuciones(EJECUCIONES_A_REVISAR)
        except Exception as e:  # el adaptador (sqlite) no debe impedir la revisión del lector
            log.exception("no se pudo leer el historial de ejecuciones")
            return replace(resultado, error_reporte=f"{type(e).__name__}: {e}")
        reporte = revisar_reporte(ejecuciones, ahora, self._plazo_reporte)
        if reporte is not None:
            log.log(
                logging.WARNING if reporte.pendiente else logging.INFO,
                "control del reporte semanal",
                extra={
                    "periodo": reporte.periodo.etiqueta(),
                    "ultima_ejecucion": (
                        reporte.ultima_ejecucion.isoformat() if reporte.ultima_ejecucion else None
                    ),
                },
            )
        return replace(resultado, reporte=reporte)
