"""Revisión diaria: ¿hoy le han llegado marcaciones a HikCentral? Si no, avisa al administrador.

No importa smtplib, jinja2 ni el formato del log de HikCentral: solo puertos (ADR-0006).
"""

import logging
from dataclasses import dataclass, replace

from asistencia_bot.domain.errores import ErrorBot, ErrorLectura
from asistencia_bot.domain.vigilancia import EstadoLector, revisar_lector
from asistencia_bot.ports import FuenteEventos, Notificador, Reloj, RenderizadorCorreos

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResultadoVigilancia:
    estado: EstadoLector | None
    error: str | None = None  # no se pudo revisar
    alerta_enviada: bool = False
    error_envio: str | None = None

    @property
    def hay_problema(self) -> bool:
        return self.error is not None or (self.estado is not None and self.estado.sin_marcaciones)

    @property
    def codigo_salida(self) -> int:
        """0 hay marcaciones, 1 no hay o no se pudo revisar, 2 había que avisar y no se pudo."""
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
    ) -> None:
        self._reloj = reloj
        self._fuente = fuente
        self._notificador = notificador
        self._renderizador = renderizador
        self._admin = administrador

    def ejecutar(self, *, avisar: bool = True) -> ResultadoVigilancia:
        ahora = self._reloj.ahora()
        desde = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            resultado = ResultadoVigilancia(revisar_lector(self._fuente.muestras(), desde))
        except ErrorLectura as e:
            resultado = ResultadoVigilancia(None, error=str(e))
        estado = resultado.estado
        log.log(
            logging.WARNING if resultado.hay_problema else logging.INFO,
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
        if not resultado.hay_problema or not avisar:
            return resultado
        if self._notificador is None or not self._admin:
            return replace(resultado, error_envio="no hay SMTP o administrador configurado")
        try:
            correo = self._renderizador.correo_alerta_lector(
                self._admin, ahora, estado, resultado.error
            )
            self._notificador.enviar(correo)
        except ErrorBot as e:
            log.error("alerta del lector no enviada", extra={"error": str(e)})
            return replace(resultado, error_envio=str(e))
        return replace(resultado, alerta_enviada=True)
