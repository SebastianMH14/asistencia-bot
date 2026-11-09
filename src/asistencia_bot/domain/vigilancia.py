"""Revisiones diarias: ¿llegan marcaciones a HikCentral (ADR-0006) y salió el reporte (ADR-0008)?

El lector puede dejar de enviar eventos sin que HikCentral lo marque desconectado. Sin eventos no
hay registros de asistencia, así que conviene detectarlo el mismo día y no el lunes siguiente.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from asistencia_bot.domain.modelos import Ejecucion, Modo, Periodo
from asistencia_bot.domain.periodo import semana_anterior


@dataclass(frozen=True, slots=True)
class MuestraEventos:
    """Una línea de estadística de HikCentral: eventos recibidos en una ventana de ~30 s."""

    momento: datetime
    eventos: int


@dataclass(frozen=True, slots=True)
class EstadoLector:
    desde: datetime
    eventos: int
    ultimo_evento: datetime | None  # en todo el log; None si no hay ninguno

    @property
    def sin_marcaciones(self) -> bool:
        return self.eventos == 0


def revisar_lector(muestras: Iterable[MuestraEventos], desde: datetime) -> EstadoLector:
    eventos = 0
    ultimo: datetime | None = None
    for muestra in muestras:
        if muestra.eventos <= 0:
            continue
        if ultimo is None or muestra.momento > ultimo:
            ultimo = muestra.momento
        if muestra.momento >= desde:
            eventos += muestra.eventos
    return EstadoLector(desde, eventos, ultimo)


@dataclass(frozen=True, slots=True)
class EstadoReporte:
    periodo: Periodo
    ultima_ejecucion: datetime | None  # inicio de la última ejecución de producción terminada

    @property
    def pendiente(self) -> bool:
        return self.ultima_ejecucion is None


def revisar_reporte(
    ejecuciones: Iterable[Ejecucion], ahora: datetime, plazo: time
) -> EstadoReporte | None:
    """Estado del reporte de la semana anterior; ``None`` si aún no vence el plazo del lunes.

    Basta una ejecución de producción terminada de ese periodo, aunque tuviera fallos: esa ya le
    mandó el resumen al administrador. Lo que se busca es el silencio (ADR-0008): la tarea no
    corrió, Windows bloqueó el programa o el bot murió sin terminar.
    """
    periodo = semana_anterior(ahora.date())
    lunes = periodo.hasta + timedelta(days=1)
    if ahora < datetime.combine(lunes, plazo, tzinfo=ahora.tzinfo):
        return None
    inicios = [
        e.inicio
        for e in ejecuciones
        if e.modo is Modo.PRODUCCION and e.periodo == periodo and e.fin is not None
    ]
    return EstadoReporte(periodo, max(inicios, default=None))
