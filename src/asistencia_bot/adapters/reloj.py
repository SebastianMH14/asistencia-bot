"""Reloj del sistema con zona horaria explícita (Windows necesita el paquete tzdata)."""

from datetime import datetime
from zoneinfo import ZoneInfo


class RelojSistema:
    def __init__(self, zona: str) -> None:
        self._zona = ZoneInfo(zona)

    def ahora(self) -> datetime:
        return datetime.now(self._zona)
