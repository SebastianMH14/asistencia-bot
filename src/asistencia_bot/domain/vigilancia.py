"""¿Le están llegando marcaciones a HikCentral? (ADR-0006).

El lector puede dejar de enviar eventos sin que HikCentral lo marque desconectado. Sin eventos no
hay registros de asistencia, así que conviene detectarlo el mismo día y no el lunes siguiente.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


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
