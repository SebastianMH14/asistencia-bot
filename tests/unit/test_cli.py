"""CLI: códigos de salida, bloqueos de modo, candado, estado y verificar (todo con fakes)."""

from datetime import date, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from asistencia_bot import bootstrap, cli
from asistencia_bot.adapters.candado import CandadoArchivo
from asistencia_bot.adapters.estado_sqlite import EstadoSqlite
from asistencia_bot.domain.modelos import Ejecucion, EstadoGrupo, Modo, Periodo, ResultadoGrupo
from asistencia_bot.services.ejecutar_reporte_semanal import OpcionesEjecucion

runner = CliRunner()
SEMANA = Periodo(date(2026, 10, 12), date(2026, 10, 18))
SMTP = """
[smtp]
host = "smtp.x.co"
usuario = "bot@x.co"
remitente = "Bot <bot@x.co>"
[administrador]
correo = "admin@x.co"
"""


def _config(tmp_path: Path, extra: str = "") -> Path:
    carpeta = tmp_path / "config"
    carpeta.mkdir(exist_ok=True)
    (carpeta / "settings.toml").write_text(
        f"[hikcentral]\ncarpeta_descargas = '{tmp_path}'\n{extra}", encoding="utf-8"
    )
    (carpeta / "grupos.yaml").write_text(
        "grupos:\n  - {nombre: Fisioterapeutas, departamento_hik: Fisioterapeutas}\n",
        encoding="utf-8",
    )
    return carpeta / "settings.toml"


class ServicioFalso:
    def __init__(self, estado: EstadoGrupo) -> None:
        self.estado = estado
        self.opciones: OpcionesEjecucion | None = None

    def ejecutar(self, opciones: OpcionesEjecucion) -> Ejecucion:
        self.opciones = opciones
        e = Ejecucion("abc", datetime(2026, 10, 19, 7), opciones.modo, SEMANA, "0.1.0")
        e.resultados.append(ResultadoGrupo("Fisioterapeutas", self.estado, filas=65))
        e.fin = datetime(2026, 10, 19, 7, 1)
        return e


@pytest.fixture
def servicio(monkeypatch: pytest.MonkeyPatch) -> ServicioFalso:
    falso = ServicioFalso(EstadoGrupo.VALIDADO_SIN_ENVIO)
    monkeypatch.setattr(bootstrap, "construir_servicio", lambda cfg, modo, visible=False: falso)
    monkeypatch.setattr(cli, "configurar_logging", lambda *a, **k: None)
    return falso


def test_dry_run(tmp_path: Path, servicio: ServicioFalso) -> None:
    r = runner.invoke(
        cli.app, ["ejecutar", "--dry-run", "-g", "Fisioterapeutas", "-c", str(_config(tmp_path))]
    )

    assert r.exit_code == 0, r.output
    assert servicio.opciones == OpcionesEjecucion(Modo.DRY_RUN, False, ("Fisioterapeutas",))
    assert "VALIDADO_SIN_ENVIO" in r.output


def test_fallo_parcial_sale_con_1(tmp_path: Path, servicio: ServicioFalso) -> None:
    servicio.estado = EstadoGrupo.FALLIDO

    r = runner.invoke(cli.app, ["ejecutar", "--dry-run", "-c", str(_config(tmp_path))])

    assert r.exit_code == 1


def test_modo_por_defecto_prueba_exige_smtp(tmp_path: Path, servicio: ServicioFalso) -> None:
    r = runner.invoke(cli.app, ["ejecutar", "-c", str(_config(tmp_path))])

    assert r.exit_code == 2
    assert "falta la sección [smtp]" in r.output
    assert servicio.opciones is None


def test_prueba_con_smtp(tmp_path: Path, servicio: ServicioFalso) -> None:
    r = runner.invoke(cli.app, ["ejecutar", "--forzar", "-c", str(_config(tmp_path, SMTP))])

    assert r.exit_code == 0, r.output
    assert servicio.opciones == OpcionesEjecucion(Modo.PRUEBA, True, ())


def test_produccion_bloqueada_sin_habilitar(tmp_path: Path, servicio: ServicioFalso) -> None:
    r = runner.invoke(
        cli.app, ["ejecutar", "--modo", "produccion", "-c", str(_config(tmp_path, SMTP))]
    )

    assert r.exit_code == 2
    assert "no está habilitado" in r.output


def test_candado_ocupado(tmp_path: Path, servicio: ServicioFalso) -> None:
    config = _config(tmp_path)
    with CandadoArchivo(tmp_path / "ejecucion.lock"):
        r = runner.invoke(cli.app, ["ejecutar", "--dry-run", "-c", str(config)])

    assert r.exit_code == 2
    assert "ya hay una ejecución en curso" in r.output


def test_config_inexistente(tmp_path: Path) -> None:
    r = runner.invoke(cli.app, ["ejecutar", "--dry-run", "-c", str(tmp_path / "no.toml")])

    assert r.exit_code == 2
    assert "settings.example.toml" in r.output


def test_estado(tmp_path: Path) -> None:
    config = _config(tmp_path)
    vacio = runner.invoke(cli.app, ["estado", "-c", str(config)])
    db = EstadoSqlite(tmp_path / "estado.db")
    e = Ejecucion(
        "abcdef123", datetime(2026, 10, 19, 7), Modo.PRUEBA, SEMANA, "0.1.0", error_fatal="algo"
    )
    db.iniciar_ejecucion(e)
    db.registrar_resultado(e, ResultadoGrupo("Fisioterapeutas", EstadoGrupo.FALLIDO, error="x"))
    db.finalizar_ejecucion(e)

    r = runner.invoke(cli.app, ["estado", "-c", str(config)])

    assert "No hay ejecuciones" in vacio.output
    assert "código 2" in r.output and "[abcdef12]" in r.output
    assert "Fisioterapeutas: FALLIDO — x" in r.output
    assert "error fatal: algo" in r.output


class Credenciales:
    def __init__(self, claves: dict[str, str]) -> None:
        self.claves = claves

    def obtener(self, sistema: str, usuario: str) -> str | None:
        return self.claves.get(sistema)

    def guardar(self, sistema: str, usuario: str, secreto: str) -> None: ...

    def borrar(self, sistema: str, usuario: str) -> bool:
        return False


@pytest.fixture
def entorno_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "puerto_abierto", lambda puerto: True)
    monkeypatch.setattr(cli, "hikcentral_responde", lambda url, host: None)


def test_verificar_todo_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entorno_ok: None
) -> None:
    class SmtpOk:
        def probar(self) -> None: ...

    monkeypatch.setattr(
        bootstrap,
        "crear_almacen_credenciales",
        lambda: Credenciales({"hikcentral": "x", "smtp": "y"}),
    )
    monkeypatch.setattr(bootstrap, "crear_notificador", lambda a, c: SmtpOk())

    r = runner.invoke(cli.app, ["verificar", "-c", str(_config(tmp_path, SMTP))])

    assert r.exit_code == 0, r.output
    assert "FALLA" not in r.output


def test_verificar_detecta_faltantes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "crear_almacen_credenciales", lambda: Credenciales({}))
    monkeypatch.setattr(cli, "puerto_abierto", lambda puerto: False)
    monkeypatch.setattr(cli, "hikcentral_responde", lambda url, host: "HikCentral no responde")

    r = runner.invoke(cli.app, ["verificar", "-c", str(_config(tmp_path))])

    assert r.exit_code == 2
    for texto in ("contraseña de HikCentral", "HCWebControl", "HikCentral no responde", "[smtp]"):
        assert texto in r.output
