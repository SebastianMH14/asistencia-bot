"""Composition root: el único lugar que elige e instancia adaptadores concretos."""

from asistencia_bot.adapters.credenciales_keyring import AlmacenKeyring
from asistencia_bot.ports import AlmacenCredenciales


def crear_almacen_credenciales() -> AlmacenCredenciales:
    return AlmacenKeyring()
