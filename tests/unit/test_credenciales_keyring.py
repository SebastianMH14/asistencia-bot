"""Adaptador de keyring con un backend en memoria: nunca toca el Administrador real."""

from collections.abc import Iterator

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from asistencia_bot.adapters.credenciales_keyring import AlmacenKeyring, nombre_servicio


class KeyringEnMemoria(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.datos: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.datos.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.datos[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.datos:
            raise PasswordDeleteError("no existe")
        del self.datos[(service, username)]


@pytest.fixture
def backend() -> Iterator[KeyringEnMemoria]:
    anterior = keyring.get_keyring()
    en_memoria = KeyringEnMemoria()
    keyring.set_keyring(en_memoria)
    yield en_memoria
    keyring.set_keyring(anterior)


def test_guarda_bajo_servicio_con_prefijo(backend: KeyringEnMemoria) -> None:
    AlmacenKeyring().guardar("hikcentral", "admin", "x")

    assert backend.datos == {("asistencia-bot/hikcentral", "admin"): "x"}
    assert nombre_servicio("smtp") == "asistencia-bot/smtp"


def test_obtener_y_borrar(backend: KeyringEnMemoria) -> None:
    almacen = AlmacenKeyring()
    assert almacen.obtener("hikcentral", "admin") is None

    almacen.guardar("hikcentral", "admin", "x")
    assert almacen.obtener("hikcentral", "admin") == "x"

    assert almacen.borrar("hikcentral", "admin") is True
    assert almacen.borrar("hikcentral", "admin") is False
