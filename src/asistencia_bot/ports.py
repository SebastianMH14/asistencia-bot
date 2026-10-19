"""Puertos del hexágono: lo que el dominio y los servicios necesitan del exterior.

Los adaptadores concretos (keyring, Playwright, SMTP, SQLite) viven en ``adapters/``
y se conectan en ``bootstrap.py``.
"""

from typing import Protocol


class AlmacenCredenciales(Protocol):
    """Guarda y recupera secretos por sistema (``hikcentral``, ``smtp``) y usuario."""

    def obtener(self, sistema: str, usuario: str) -> str | None:
        """Devuelve el secreto o ``None`` si no hay ninguno guardado."""
        ...

    def guardar(self, sistema: str, usuario: str, secreto: str) -> None:
        """Crea o reemplaza el secreto."""
        ...

    def borrar(self, sistema: str, usuario: str) -> bool:
        """Elimina el secreto; devuelve ``False`` si no existía."""
        ...
