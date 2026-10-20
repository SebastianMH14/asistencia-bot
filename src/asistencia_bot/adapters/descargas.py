"""Captura del Excel vigilando la carpeta Downloadcenter de HCWebControl (ADR-0002).

Solo lee la carpeta: nunca mueve, renombra ni borra nada en ella.
"""

import time
from collections.abc import Callable
from pathlib import Path

from asistencia_bot.domain.errores import ErrorCaptura, ErrorEntorno


class VigilanteDescargas:
    def __init__(
        self,
        carpeta: Path,
        prefijo: str,
        *,
        intervalo_s: float = 0.5,
        sondeos_estables: int = 3,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._carpeta = carpeta
        self._prefijo = f"{prefijo}_"
        self._intervalo = intervalo_s
        self._sondeos = sondeos_estables
        self._dormir = dormir
        self._reloj = reloj

    def instantanea(self) -> frozenset[str]:
        """Subcarpetas existentes antes de pulsar Exportar."""
        if not self._carpeta.is_dir():
            raise ErrorEntorno(f"no existe la carpeta de descargas {self._carpeta}")
        return frozenset(p.name for p in self._carpeta.iterdir())

    def _nuevas(self, antes: frozenset[str]) -> list[Path]:
        nuevas = [
            p
            for p in self._carpeta.iterdir()
            if p.is_dir() and p.name not in antes and p.name.startswith(self._prefijo)
        ]
        return sorted(nuevas, key=lambda p: p.stat().st_mtime, reverse=True)

    def esperar(self, antes: frozenset[str], nombre_esperado: str, limite_s: float) -> Path:
        """Devuelve el .xlsx esperado cuando su tamaño no cambia en N sondeos seguidos."""
        fin = self._reloj() + limite_s
        tamanos: dict[Path, int] = {}
        estables: dict[Path, int] = {}
        vistos: set[str] = set()
        while self._reloj() < fin:
            for carpeta in self._nuevas(antes):
                for archivo in carpeta.glob("*.xlsx"):
                    vistos.add(archivo.name)
                    if archivo.name != nombre_esperado:
                        continue
                    try:
                        tamano = archivo.stat().st_size
                        with archivo.open("rb"):
                            pass
                    except OSError:
                        estables[archivo] = 0
                        continue
                    previo = tamanos.get(archivo)
                    estables[archivo] = estables.get(archivo, 0) + 1 if previo == tamano else 0
                    tamanos[archivo] = tamano
                    if tamano > 0 and estables[archivo] >= self._sondeos:
                        return archivo
            self._dormir(self._intervalo)
        otros = sorted(vistos - {nombre_esperado})
        detalle = f"; apareció en cambio: {', '.join(otros)}" if otros else ""
        raise ErrorCaptura(f"no apareció {nombre_esperado!r} estable en {limite_s:.0f} s{detalle}")
