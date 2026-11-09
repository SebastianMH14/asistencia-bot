"""Vigilancia diaria: lector (ADR-0006) y reporte semanal (ADR-0008). Dominio, log de HikCentral,
servicio, correos y CLI."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from asistencia_bot import bootstrap, cli
from asistencia_bot.adapters.log_eventos_hik import LogEventosHik
from asistencia_bot.adapters.plantillas import GUION, RenderizadorJinja
from asistencia_bot.domain.errores import ErrorLectura, ErrorNotificacion
from asistencia_bot.domain.modelos import Correo, Ejecucion, Modo, Periodo
from asistencia_bot.domain.vigilancia import (
    EstadoLector,
    EstadoReporte,
    MuestraEventos,
    revisar_lector,
    revisar_reporte,
)
from asistencia_bot.services.vigilar_lector import VigilarLector

Z = ZoneInfo("America/Bogota")
MIERCOLES = datetime(2026, 10, 21, 10, 0, tzinfo=Z)
HOY = datetime(2026, 10, 21, 0, 0, tzinfo=Z)
CAIDA = datetime(2026, 10, 20, 16, 44, 8, tzinfo=Z)
SEMANA = Periodo(date(2026, 10, 12), date(2026, 10, 18))  # la anterior a MIERCOLES
NUEVE = time(9, 0)


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


def _ejecucion(
    modo: Modo = Modo.PRODUCCION,
    periodo: Periodo = SEMANA,
    inicio: datetime = datetime(2026, 10, 19, 5, 0, 30, tzinfo=Z),
    *,
    terminada: bool = True,
) -> Ejecucion:
    fin = inicio + timedelta(minutes=2) if terminada else None
    return Ejecucion("e1", inicio, modo, periodo, "0.1.0", fin=fin)


def test_revisar_reporte_antes_del_plazo_del_lunes_no_revisa() -> None:
    lunes = datetime(2026, 10, 19, 8, 59, tzinfo=Z)

    assert revisar_reporte([], lunes, NUEVE) is None
    assert revisar_reporte([], lunes.replace(hour=9, minute=0), NUEVE) == EstadoReporte(
        SEMANA, None
    )


def test_revisar_reporte_cuenta_solo_produccion_terminada_de_la_semana_anterior() -> None:
    sabado = datetime(2026, 10, 24, 10, 0, tzinfo=Z)  # sigue revisando la misma semana
    otras = [
        _ejecucion(Modo.PRUEBA),
        _ejecucion(Modo.DRY_RUN),
        _ejecucion(periodo=Periodo(date(2026, 10, 5), date(2026, 10, 11))),
        _ejecucion(terminada=False),  # murió sin terminar: no avisó a nadie
    ]
    buena = _ejecucion(inicio=datetime(2026, 10, 21, 8, 17, tzinfo=Z))

    pendiente = revisar_reporte(otras, sabado, NUEVE)
    hecho = revisar_reporte([*otras, _ejecucion(), buena], sabado, NUEVE)

    assert pendiente is not None and pendiente.pendiente and pendiente.periodo == SEMANA
    assert hecho is not None and not hecho.pendiente
    assert hecho.ultima_ejecucion == buena.inicio


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


@dataclass
class Estado:
    ejecuciones: list[Ejecucion] = field(default_factory=list)
    error: Exception | None = None

    def ultimas_ejecuciones(self, n: int) -> list[Ejecucion]:
        if self.error:
            raise self.error
        return self.ejecuciones[:n]


def _servicio(
    fuente: Fuente,
    notificador: Notificador | None,
    admin: str | None = "admin@x.co",
    estado: Estado | None = None,
) -> VigilarLector:
    return VigilarLector(
        reloj=Reloj(),
        fuente=fuente,
        notificador=notificador,
        renderizador=RenderizadorJinja("0.1.0"),
        administrador=admin,
        estado=estado,  # type: ignore[arg-type]  # el fake solo implementa lo que se usa
        plazo_reporte=NUEVE if estado is not None else None,
    )


CON_MARCACIONES = [MuestraEventos(datetime(2026, 10, 21, 7, tzinfo=Z), 12)]


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


def test_reporte_sin_salir_avisa_aunque_haya_marcaciones() -> None:
    notificador = Notificador()

    r = _servicio(Fuente(CON_MARCACIONES), notificador, estado=Estado([])).ejecutar()

    assert r.codigo_salida == 1 and r.reporte_pendiente
    assert r.alerta_reporte_enviada and not r.alerta_enviada
    [correo] = notificador.enviados
    assert correo.para == ("admin@x.co",)
    assert "el reporte semanal no salió (semana 12/10 al 18/10)" in correo.asunto


def test_reporte_que_ya_corrio_no_avisa() -> None:
    notificador = Notificador()

    r = _servicio(Fuente(CON_MARCACIONES), notificador, estado=Estado([_ejecucion()])).ejecutar()

    assert r.codigo_salida == 0 and notificador.enviados == []
    assert r.reporte is not None and r.reporte.ultima_ejecucion is not None


def test_lector_y_reporte_avisan_por_separado() -> None:
    notificador = Notificador()

    r = _servicio(Fuente(), notificador, estado=Estado([])).ejecutar()

    assert r.codigo_salida == 1 and r.alerta_enviada and r.alerta_reporte_enviada
    asuntos = [c.asunto for c in notificador.enviados]
    assert len(asuntos) == 2
    assert "lector" in asuntos[0] and "reporte semanal" in asuntos[1]


def test_historial_ilegible_no_impide_revisar_el_lector() -> None:
    notificador = Notificador()
    estado = Estado(error=RuntimeError("database is locked"))

    r = _servicio(Fuente(), notificador, estado=estado).ejecutar()

    assert r.error_reporte == "RuntimeError: database is locked" and r.reporte is None
    assert r.codigo_salida == 1 and r.alerta_enviada  # el aviso del lector sí sale
    assert len(notificador.enviados) == 1


def test_no_poder_avisar_del_reporte_da_codigo_2() -> None:
    notificador = Notificador(error=ErrorNotificacion("smtp"))

    r = _servicio(Fuente(CON_MARCACIONES), notificador, estado=Estado([])).ejecutar()

    assert r.codigo_salida == 2 and not r.alerta_reporte_enviada


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


def test_correo_alerta_reporte() -> None:
    correo = RenderizadorJinja("0.1.0").correo_alerta_reporte(
        "a@x.co", MIERCOLES, EstadoReporte(SEMANA, None)
    )

    assert correo.para == ("a@x.co",) and correo.adjuntos == ()
    assert correo.asunto == (
        f"[asistencia-bot] ALERTA {GUION} el reporte semanal no salió (semana 12/10 al 18/10)"
    )
    assert "Hoy, miércoles 21/10/2026 a las 10:00" in correo.texto
    assert "semana del 12/10/2026 al 18/10/2026" in correo.texto
    assert "Programador de tareas" in correo.html and "Ejecutar" in correo.html


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
    assert "Reporte de la semana" not in resultado.output  # en modo prueba no se revisa


def test_cli_en_produccion_revisa_el_reporte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "EventStatistics.log"
    log.write_text(_linea("2026-10-21 07:00:00", 7))
    config = tmp_path / "config" / "settings.toml"
    config.parent.mkdir()
    config.write_text(
        '[ejecucion]\nmodo_por_defecto = "produccion"\nproduccion_habilitada = true\n'
        f"[rutas]\nbase = '{tmp_path}'\n[vigilancia]\nlog_eventos = '{log}'\n",
        encoding="utf-8",
    )
    (config.parent / "grupos.yaml").write_text(
        "grupos:\n  - {nombre: Fisioterapeutas, departamento_hik: Fisioterapeutas}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "RelojSistema", lambda zona: Reloj())
    monkeypatch.setattr(cli, "configurar_logging", lambda *a, **k: None)

    resultado = CliRunner().invoke(cli.app, ["vigilar-lector", "--sin-correo", "-c", str(config)])

    assert resultado.exit_code == 1, resultado.output
    assert "Reporte de la semana 2026-10-12 al 2026-10-18: NO ha salido" in resultado.output
    assert (tmp_path / "estado.db").exists()
