"""Vigilancia del lector: dominio, lectura del log de HikCentral, servicio, correo y CLI."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from asistencia_bot import bootstrap, cli
from asistencia_bot.adapters.log_eventos_hik import LogEventosHik
from asistencia_bot.adapters.plantillas import GUION, RenderizadorJinja
from asistencia_bot.domain.errores import ErrorLectura, ErrorNotificacion
from asistencia_bot.domain.modelos import Correo
from asistencia_bot.domain.vigilancia import EstadoLector, MuestraEventos, revisar_lector
from asistencia_bot.services.vigilar_lector import VigilarLector

Z = ZoneInfo("America/Bogota")
MIERCOLES = datetime(2026, 10, 21, 10, 0, tzinfo=Z)
HOY = datetime(2026, 10, 21, 0, 0, tzinfo=Z)
CAIDA = datetime(2026, 10, 20, 16, 44, 8, tzinfo=Z)


def _linea(momento: str, eventos: int) -> str:
    """Formato real del log de HikCentral (solo conteos)."""
    return (
        f"[{momento}.337][baseacs.d.EventStatistics][INFO][baseacsDAM::SPEventProcessPrivate::"
        f"TimePrintLog]Last 30 s,\treceive 0 succ(avg:0/s),\t{eventos} input(avg:0/s)"
        "[..\\..\\..\\src\\EventProcess\\SPEventProcessImp.cpp(426)][0x00003db8]\n"
    )


# --- dominio ------------------------------------------------------------------------------


def test_revisar_lector_cuenta_solo_desde_el_inicio_del_dia() -> None:
    muestras = [
        MuestraEventos(CAIDA, 1),
        MuestraEventos(datetime(2026, 10, 21, 7, 0, tzinfo=Z), 0),  # canal vivo, sin eventos
        MuestraEventos(datetime(2026, 10, 21, 7, 30, tzinfo=Z), 5),
    ]

    estado = revisar_lector(muestras, HOY)

    assert estado.eventos == 5 and not estado.sin_marcaciones
    assert estado.ultimo_evento == datetime(2026, 10, 21, 7, 30, tzinfo=Z)


def test_revisar_lector_sin_marcaciones_hoy() -> None:
    estado = revisar_lector([MuestraEventos(CAIDA, 1)], HOY)

    assert estado.sin_marcaciones and estado.ultimo_evento == CAIDA
    assert revisar_lector([], HOY).ultimo_evento is None


# --- adaptador ----------------------------------------------------------------------------


def test_lee_el_log_de_hikcentral(tmp_path: Path) -> None:
    log = tmp_path / "EventStatistics.log"
    log.write_text(
        _linea("2026-10-20 16:44:08", 1)
        + "[2026-10-20 16:44:09.000][baseacs.d.EventStatistics][INFO][Otra cosa] sin conteo\n"
        + _linea("2026-10-26 08:35:18", 5),
        encoding="utf-8",
    )

    muestras = LogEventosHik(log, "America/Bogota").muestras()

    assert muestras == [
        MuestraEventos(CAIDA, 1),
        MuestraEventos(datetime(2026, 10, 26, 8, 35, 18, tzinfo=Z), 5),
    ]


def test_log_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ErrorLectura, match="no se pudo leer"):
        LogEventosHik(tmp_path / "no-existe.log", "America/Bogota").muestras()


# --- servicio -----------------------------------------------------------------------------


class Reloj:
    def ahora(self) -> datetime:
        return MIERCOLES


@dataclass
class Fuente:
    muestras_: list[MuestraEventos] = field(default_factory=list)
    error: Exception | None = None

    def muestras(self) -> list[MuestraEventos]:
        if self.error:
            raise self.error
        return self.muestras_


@dataclass
class Notificador:
    enviados: list[Correo] = field(default_factory=list)
    error: Exception | None = None

    def enviar(self, correo: Correo) -> None:
        if self.error:
            raise self.error
        self.enviados.append(correo)


def _servicio(
    fuente: Fuente, notificador: Notificador | None, admin: str | None = "admin@x.co"
) -> VigilarLector:
    return VigilarLector(
        reloj=Reloj(),
        fuente=fuente,
        notificador=notificador,
        renderizador=RenderizadorJinja("0.1.0"),
        administrador=admin,
    )


def test_con_marcaciones_no_avisa() -> None:
    notificador = Notificador()
    fuente = Fuente([MuestraEventos(datetime(2026, 10, 21, 7, tzinfo=Z), 12)])

    r = _servicio(fuente, notificador).ejecutar()

    assert r.codigo_salida == 0 and not r.alerta_enviada
    assert notificador.enviados == []


def test_sin_marcaciones_avisa_al_administrador() -> None:
    notificador = Notificador()

    r = _servicio(Fuente([MuestraEventos(CAIDA, 1)]), notificador).ejecutar()

    assert r.codigo_salida == 1 and r.alerta_enviada
    [correo] = notificador.enviados
    assert correo.para == ("admin@x.co",)
    assert "el lector no envía marcaciones" in correo.asunto


def test_log_ilegible_tambien_avisa() -> None:
    notificador = Notificador()
    fuente = Fuente(error=ErrorLectura("no se pudo leer x.log: FileNotFoundError"))

    r = _servicio(fuente, notificador).ejecutar()

    assert r.codigo_salida == 1 and r.estado is None
    assert "no se pudo revisar el lector" in notificador.enviados[0].asunto


def test_sin_correo_no_avisa() -> None:
    notificador = Notificador()

    r = _servicio(Fuente(), notificador).ejecutar(avisar=False)

    assert r.codigo_salida == 1 and not r.alerta_enviada
    assert notificador.enviados == []


@pytest.mark.parametrize(
    ("notificador", "admin"),
    [
        (None, "admin@x.co"),
        (Notificador(), None),
        (Notificador(error=ErrorNotificacion("smtp")), "a@x.co"),
    ],
)
def test_no_poder_avisar_da_codigo_2(notificador: Notificador | None, admin: str | None) -> None:
    r = _servicio(Fuente(), notificador, admin).ejecutar()

    assert r.codigo_salida == 2 and r.error_envio


# --- correo -------------------------------------------------------------------------------


def test_correo_alerta_lector() -> None:
    estado = EstadoLector(HOY, 0, CAIDA)

    correo = RenderizadorJinja("0.1.0").correo_alerta_lector("a@x.co", MIERCOLES, estado, None)

    assert correo.asunto == (
        f"[asistencia-bot] ALERTA {GUION} el lector no envía marcaciones (21/10 10:00)"
    )
    assert "Hoy, miércoles 21/10/2026, hasta las 10:00" in correo.texto
    assert "Última marcación recibida: martes 20/10/2026 a las 16:44." in correo.texto
    assert "martes 20/10/2026 a las 16:44" in correo.html


def test_correo_alerta_sin_ninguna_marcacion_o_con_error() -> None:
    render = RenderizadorJinja("0.1.0")

    vacio = render.correo_alerta_lector("a@x.co", MIERCOLES, EstadoLector(HOY, 0, None), None)
    error = render.correo_alerta_lector("a@x.co", MIERCOLES, None, "no se pudo leer x.log")

    assert "no tiene ninguna marcación" in vacio.texto
    assert "no se pudo leer x.log" in error.texto and "log_eventos" in error.html


# --- CLI ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("eventos", "codigo"), [(7, 0), (0, 1)])
def test_cli_vigilar_lector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, eventos: int, codigo: int
) -> None:
    log = tmp_path / "EventStatistics.log"
    log.write_text(_linea("2026-10-20 16:44:08", 1) + _linea("2026-10-21 07:00:00", eventos))
    config = tmp_path / "settings.toml"
    config.write_text(f"[vigilancia]\nlog_eventos = '{log}'\n", encoding="utf-8")
    (tmp_path / "grupos.yaml").write_text(
        "grupos:\n  - {nombre: Fisioterapeutas, departamento_hik: Fisioterapeutas}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "RelojSistema", lambda zona: Reloj())
    monkeypatch.setattr(cli, "configurar_logging", lambda *a, **k: None)

    resultado = CliRunner().invoke(cli.app, ["vigilar-lector", "--sin-correo", "-c", str(config)])

    assert resultado.exit_code == codigo
    assert f"Marcaciones desde 2026-10-21 00:00: {eventos}" in resultado.output
