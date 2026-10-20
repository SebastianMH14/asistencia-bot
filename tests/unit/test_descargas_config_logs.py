import json
import logging
from pathlib import Path

import pytest

from asistencia_bot.adapters.descargas import VigilanteDescargas
from asistencia_bot.config import cargar
from asistencia_bot.domain.errores import ErrorCaptura, ErrorConfiguracion, ErrorEntorno
from asistencia_bot.domain.modelos import Modo, PoliticaSinRegistros
from asistencia_bot.logging_config import configurar_logging

REPORTE = "Registros de entradas y salidas"
ESPERADO = f"{REPORTE}_2026-10-12_2026-10-18.xlsx"


# --- vigilante de descargas ---------------------------------------------------------------


class RelojFalso:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _vigilante(carpeta: Path, al_dormir: list[object]) -> tuple[VigilanteDescargas, RelojFalso]:
    reloj = RelojFalso()

    def dormir(s: float) -> None:
        reloj.t += s
        if al_dormir:
            accion = al_dormir.pop(0)
            if callable(accion):
                accion()

    return VigilanteDescargas(carpeta, REPORTE, dormir=dormir, reloj=reloj), reloj


def test_espera_archivo_estable(tmp_path: Path) -> None:
    (tmp_path / f"{REPORTE}_2026_10_05_07_00_00").mkdir()  # exportación anterior
    vigilante, _ = _vigilante(tmp_path, [])
    antes = vigilante.instantanea()
    nueva = tmp_path / f"{REPORTE}_2026_10_19_07_00_00"
    archivo = nueva / ESPERADO

    def crear() -> None:
        nueva.mkdir()
        archivo.write_bytes(b"a" * 10)

    def crecer() -> None:
        archivo.write_bytes(b"a" * 20)

    vigilante, _ = _vigilante(tmp_path, [crear, crecer])

    assert vigilante.esperar(antes, ESPERADO, limite_s=60) == archivo


def test_timeout_informa_otros_archivos(tmp_path: Path) -> None:
    vigilante, _ = _vigilante(tmp_path, [])
    antes = vigilante.instantanea()
    otra = tmp_path / f"{REPORTE}_2026_10_19_07_00_00"
    otra.mkdir()
    (otra / f"{REPORTE}_2026-10-05_2026-10-11.xlsx").write_bytes(b"x")

    with pytest.raises(ErrorCaptura, match="apareció en cambio"):
        vigilante.esperar(antes, ESPERADO, limite_s=5)


def test_ignora_carpetas_previas_y_de_otros_reportes(tmp_path: Path) -> None:
    previa = tmp_path / f"{REPORTE}_2026_10_19_06_00_00"
    previa.mkdir()
    (previa / ESPERADO).write_bytes(b"viejo")
    vigilante, _ = _vigilante(tmp_path, [])
    antes = vigilante.instantanea()
    otro = tmp_path / "Transacciones_2026_10_19_07_00_00"
    otro.mkdir()
    (otro / ESPERADO).write_bytes(b"x")

    with pytest.raises(ErrorCaptura):
        vigilante.esperar(antes, ESPERADO, limite_s=3)


def test_carpeta_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ErrorEntorno):
        VigilanteDescargas(tmp_path / "no", REPORTE).instantanea()


# --- configuración ------------------------------------------------------------------------

SETTINGS = """
[hikcentral]
usuario = "bot"
[ejecucion]
modo_por_defecto = "prueba"
sin_registros = "enviar_aviso_sin_registros"
[smtp]
host = "smtp.x.co"
usuario = "bot@x.co"
remitente = "Bot <bot@x.co>"
[administrador]
correo = "admin@x.co"
"""
GRUPOS = """
grupos:
  - nombre: Fisioterapeutas
    departamento_hik: Fisioterapeutas
    jefe: {nombre: Jefa, correo: jefa@x.co}
    cc: [cc@x.co]
  - nombre: TI
    departamento_hik: TI
    activo: false
"""


def _config(tmp_path: Path, settings: str = SETTINGS, grupos: str = GRUPOS) -> Path:
    carpeta = tmp_path / "proyecto" / "config"
    carpeta.mkdir(parents=True)
    (carpeta / "settings.toml").write_text(settings, encoding="utf-8")
    (carpeta / "grupos.yaml").write_text(grupos, encoding="utf-8")
    return carpeta / "settings.toml"


def test_carga_config_y_grupos(tmp_path: Path) -> None:
    cfg = cargar(_config(tmp_path))

    assert cfg.ajustes.hikcentral.usuario == "bot"
    assert cfg.ajustes.hikcentral.host == "127.0.0.1"
    assert cfg.ajustes.rutas.base == (tmp_path / "proyecto").resolve()
    assert cfg.ajustes.rutas.salida.name == "salida"
    assert cfg.ajustes.ejecucion.sin_registros is PoliticaSinRegistros.ENVIAR_AVISO
    assert [g.nombre for g in cfg.grupos_activos] == ["Fisioterapeutas"]
    assert cfg.grupos_activos[0].destinatarios == ("jefa@x.co", "cc@x.co")
    assert cfg.problemas_para_modo(Modo.PRUEBA) == []
    assert "no está habilitado" in cfg.problemas_para_modo(Modo.PRODUCCION)[0]


def test_carpeta_de_descargas_por_defecto_en_el_perfil(tmp_path: Path) -> None:
    cfg = cargar(_config(tmp_path))

    assert cfg.ajustes.hikcentral.carpeta_descargas == (
        Path.home() / "HCWebControlService" / "Downloadcenter"
    )


def test_los_ejemplos_versionados_cargan(tmp_path: Path) -> None:
    raiz = Path(__file__).resolve().parents[2] / "config"
    settings = (raiz / "settings.example.toml").read_text(encoding="utf-8")
    grupos = (raiz / "grupos.example.yaml").read_text(encoding="utf-8")

    cfg = cargar(_config(tmp_path, settings, grupos))

    assert len(cfg.grupos_activos) == 4
    assert cfg.problemas_para_modo(Modo.PRUEBA) == []


def test_variables_de_entorno_sobrescriben(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASISTENCIA_BOT_HIKCENTRAL__HEADLESS", "false")

    assert cargar(_config(tmp_path)).ajustes.hikcentral.headless is False


@pytest.mark.parametrize(
    ("settings", "grupos", "mensaje"),
    [
        (SETTINGS.replace("admin@x.co", "no-es-correo"), GRUPOS, "administrador.correo"),
        ('[ejecucion]\nmodo_por_defecto = "produccion"', GRUPOS, "produccion_habilitada"),
        ("[otra]\nx = 1", GRUPOS, "otra"),
        ("esto no es toml = = =", GRUPOS, "TOML inválido"),
        (
            SETTINGS,
            GRUPOS.replace("activo: false", "activo: true").replace("TI", "Fisioterapeutas"),
            "repetidos",
        ),
        (
            SETTINGS,
            "grupos: [{nombre: X, departamento_hik: X, activo: false}]",
            "ningún grupo activo",
        ),
        (SETTINGS, "grupos: [", "YAML inválido"),
    ],
)
def test_config_invalida(tmp_path: Path, settings: str, grupos: str, mensaje: str) -> None:
    with pytest.raises(ErrorConfiguracion, match=mensaje):
        cargar(_config(tmp_path, settings, grupos))


def test_config_inexistente(tmp_path: Path) -> None:
    with pytest.raises(ErrorConfiguracion, match=r"settings\.example\.toml"):
        cargar(tmp_path / "no.toml")


def test_produccion_exige_jefes(tmp_path: Path) -> None:
    settings = SETTINGS.replace('modo_por_defecto = "prueba"', "produccion_habilitada = true")
    grupos = "grupos: [{nombre: X, departamento_hik: X}]"

    cfg = cargar(_config(tmp_path, settings, grupos))

    assert cfg.problemas_para_modo(Modo.PRODUCCION) == ["grupos activos sin jefe: X"]
    assert cfg.problemas_para_modo(Modo.DRY_RUN) == []


# --- logging ------------------------------------------------------------------------------


def test_log_json_sin_call_log(tmp_path: Path) -> None:
    configurar_logging(tmp_path, consola=False)
    log = logging.getLogger("prueba")
    try:
        raise RuntimeError("Locator.click: Timeout\nCall log:\n  <td>Nombre Real</td>")
    except RuntimeError:
        log.exception("fallo", extra={"grupo": "Fisio", "filas": 65})
    for manejador in logging.getLogger().handlers:
        manejador.flush()

    linea = json.loads((tmp_path / "bot.jsonl").read_text(encoding="utf-8").splitlines()[-1])

    assert linea["evento"] == "fallo" and linea["grupo"] == "Fisio" and linea["filas"] == 65
    assert linea["excepcion"] == "RuntimeError: Locator.click: Timeout"
    assert "Nombre Real" not in json.dumps(linea)
    logging.getLogger().handlers.clear()
