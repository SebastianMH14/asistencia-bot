"""Estadísticas de eventos que HikCentral escribe en su log (solo conteos, sin datos personales).

Mientras le llegan eventos de los lectores, HikCentral escribe cada ~30 s una línea como:

    [2026-10-20 16:44:08.337][baseacs.d.EventStatistics][INFO][...::TimePrintLog]Last 30 s,
    receive 0 succ(avg:0/s), 1 input(avg:0/s)[...]

"input" son los eventos recibidos. Cuando el canal del lector se cae, deja de escribir (ADR-0006).
"""

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from asistencia_bot.domain.errores import ErrorLectura
from asistencia_bot.domain.vigilancia import MuestraEventos

LINEA = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\].*?TimePrintLog\].*?(\d+) input\b"
)


class LogEventosHik:
    def __init__(self, ruta: Path, zona: str) -> None:
        self._ruta = ruta
        self._zona = ZoneInfo(zona)

    def muestras(self) -> list[MuestraEventos]:
        try:
            with self._ruta.open(encoding="utf-8", errors="replace") as archivo:
                return [
                    MuestraEventos(
                        datetime.fromisoformat(m[1]).replace(tzinfo=self._zona), int(m[2])
                    )
                    for linea in archivo
                    if (m := LINEA.match(linea))
                ]
        except OSError as e:
            raise ErrorLectura(f"no se pudo leer {self._ruta}: {type(e).__name__}") from None
