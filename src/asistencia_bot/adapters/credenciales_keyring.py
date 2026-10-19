"""Credenciales en el Administrador de credenciales de Windows, vía ``keyring``.

El Administrador de credenciales es por usuario de Windows: la tarea programada debe
correr con el mismo usuario que ejecutó ``asistencia-bot credenciales configurar``.
"""

import keyring
from keyring.errors import PasswordDeleteError

PREFIJO_SERVICIO = "asistencia-bot"


def nombre_servicio(sistema: str) -> str:
    """Nombre con el que aparece la entrada en el Administrador de credenciales."""
    return f"{PREFIJO_SERVICIO}/{sistema}"


class AlmacenKeyring:
    """Implementa ``AlmacenCredenciales`` con el backend por defecto de keyring."""

    def obtener(self, sistema: str, usuario: str) -> str | None:
        return keyring.get_password(nombre_servicio(sistema), usuario)

    def guardar(self, sistema: str, usuario: str, secreto: str) -> None:
        keyring.set_password(nombre_servicio(sistema), usuario, secreto)

    def borrar(self, sistema: str, usuario: str) -> bool:
        try:
            keyring.delete_password(nombre_servicio(sistema), usuario)
        except PasswordDeleteError:
            return False
        return True
