"""Candado de archivo: impide dos ejecuciones simultáneas.

El sistema operativo libera el bloqueo si el proceso muere, así que no quedan candados
huérfanos aunque el archivo siga existiendo.
"""

import sys
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from asistencia_bot.domain.errores import ErrorEjecucionEnCurso

if sys.platform == "win32":
    import msvcrt

    def _bloquear(archivo: IO[bytes]) -> None:
        archivo.seek(0)
        msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)

    def _desbloquear(archivo: IO[bytes]) -> None:
        archivo.seek(0)
        msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _bloquear(archivo: IO[bytes]) -> None:
        fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _desbloquear(archivo: IO[bytes]) -> None:
        fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)


class CandadoArchivo:
    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta
        self._archivo: IO[bytes] | None = None

    def __enter__(self) -> Self:
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        archivo = self._ruta.open("a+b")
        try:
            _bloquear(archivo)
        except OSError:
            archivo.close()
            raise ErrorEjecucionEnCurso(
                f"ya hay una ejecución en curso (candado {self._ruta.name})"
            ) from None
        self._archivo = archivo
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        error: BaseException | None,
        traza: TracebackType | None,
    ) -> None:
        if self._archivo is not None:
            try:
                _desbloquear(self._archivo)
            finally:
                self._archivo.close()
                self._archivo = None
