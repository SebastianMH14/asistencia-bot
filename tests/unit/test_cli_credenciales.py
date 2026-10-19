"""CLI de credenciales con un almacén en memoria: nunca toca el Administrador real."""

import pytest
from typer.testing import CliRunner

from asistencia_bot import bootstrap
from asistencia_bot.cli import app

SECRETO = "clave-sintetica-123"

runner = CliRunner()


class AlmacenEnMemoria:
    def __init__(self) -> None:
        self.datos: dict[tuple[str, str], str] = {}

    def obtener(self, sistema: str, usuario: str) -> str | None:
        return self.datos.get((sistema, usuario))

    def guardar(self, sistema: str, usuario: str, secreto: str) -> None:
        self.datos[(sistema, usuario)] = secreto

    def borrar(self, sistema: str, usuario: str) -> bool:
        return self.datos.pop((sistema, usuario), None) is not None


@pytest.fixture
def almacen(monkeypatch: pytest.MonkeyPatch) -> AlmacenEnMemoria:
    en_memoria = AlmacenEnMemoria()
    monkeypatch.setattr(bootstrap, "crear_almacen_credenciales", lambda: en_memoria)
    return en_memoria


def _responder_getpass(monkeypatch: pytest.MonkeyPatch, *respuestas: str) -> None:
    pendientes = iter(respuestas)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(pendientes))


def test_configurar_guarda_sin_imprimir_el_secreto(
    almacen: AlmacenEnMemoria, monkeypatch: pytest.MonkeyPatch
) -> None:
    _responder_getpass(monkeypatch, SECRETO, SECRETO)

    resultado = runner.invoke(app, ["credenciales", "configurar", "hikcentral", "-u", "admin"])

    assert resultado.exit_code == 0
    assert almacen.datos == {("hikcentral", "admin"): SECRETO}
    assert SECRETO not in resultado.output


def test_configurar_rechaza_confirmacion_distinta(
    almacen: AlmacenEnMemoria, monkeypatch: pytest.MonkeyPatch
) -> None:
    _responder_getpass(monkeypatch, SECRETO, "otra")

    resultado = runner.invoke(app, ["credenciales", "configurar", "hikcentral", "-u", "admin"])

    assert resultado.exit_code == 1
    assert almacen.datos == {}
    assert "no coinciden" in resultado.output


def test_configurar_rechaza_contrasena_vacia(
    almacen: AlmacenEnMemoria, monkeypatch: pytest.MonkeyPatch
) -> None:
    _responder_getpass(monkeypatch, "")

    resultado = runner.invoke(app, ["credenciales", "configurar", "smtp", "-u", "bot@ejemplo"])

    assert resultado.exit_code == 1
    assert almacen.datos == {}


def test_comprobar_indica_si_existe_sin_mostrarla(almacen: AlmacenEnMemoria) -> None:
    sin_clave = runner.invoke(app, ["credenciales", "comprobar", "hikcentral", "-u", "admin"])
    almacen.guardar("hikcentral", "admin", SECRETO)
    con_clave = runner.invoke(app, ["credenciales", "comprobar", "hikcentral", "-u", "admin"])

    assert sin_clave.exit_code == 1
    assert con_clave.exit_code == 0
    assert SECRETO not in con_clave.output


def test_borrar(almacen: AlmacenEnMemoria) -> None:
    almacen.guardar("smtp", "bot@ejemplo", SECRETO)

    primero = runner.invoke(app, ["credenciales", "borrar", "smtp", "-u", "bot@ejemplo"])
    segundo = runner.invoke(app, ["credenciales", "borrar", "smtp", "-u", "bot@ejemplo"])

    assert primero.exit_code == 0
    assert segundo.exit_code == 1
    assert almacen.datos == {}


def test_sistema_desconocido_es_rechazado(almacen: AlmacenEnMemoria) -> None:
    resultado = runner.invoke(app, ["credenciales", "comprobar", "otro", "-u", "admin"])

    assert resultado.exit_code != 0


def test_version() -> None:
    resultado = runner.invoke(app, ["--version"])

    assert resultado.exit_code == 0
    assert "asistencia-bot" in resultado.output
