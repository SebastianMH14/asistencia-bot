import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from asistencia_bot.adapters.archivador import ArchivadorLocal, ReglaRetencion, sha256_de
from asistencia_bot.adapters.candado import CandadoArchivo
from asistencia_bot.adapters.estado_sqlite import EstadoSqlite
from asistencia_bot.domain.errores import ErrorEjecucionEnCurso
from asistencia_bot.domain.modelos import (
    Ejecucion,
    EstadoGrupo,
    Grupo,
    Modo,
    Periodo,
    ResultadoGrupo,
)

SEMANA = Periodo(date(2026, 10, 12), date(2026, 10, 18))
GRUPO = Grupo("Aux. Enfermería", "Aux. Enfermería")


# --- archivador ---------------------------------------------------------------------------


def test_archiva_byte_a_byte(tmp_path: Path) -> None:
    origen = tmp_path / "hik" / "export.xlsx"
    origen.parent.mkdir()
    origen.write_bytes(b"contenido-original")
    archivador = ArchivadorLocal(tmp_path / "salida", [])

    archivo = archivador.archivar(origen, SEMANA, GRUPO)

    assert archivo.ruta == (
        tmp_path
        / "salida"
        / "2026-10-12_2026-10-18"
        / "Asistencia_Aux_Enfermeria_2026-10-12_al_2026-10-18.xlsx"
    )
    assert archivo.ruta.read_bytes() == b"contenido-original"
    assert archivo.sha256 == sha256_de(origen)
    assert origen.exists()  # nunca se mueve el original


def test_reenvio_con_otro_contenido_conserva_el_anterior(tmp_path: Path) -> None:
    origen = tmp_path / "export.xlsx"
    archivador = ArchivadorLocal(tmp_path / "salida", [])
    origen.write_bytes(b"v1")
    primero = archivador.archivar(origen, SEMANA, GRUPO)
    mismo = archivador.archivar(origen, SEMANA, GRUPO)
    origen.write_bytes(b"v2")
    segundo = archivador.archivar(origen, SEMANA, GRUPO)

    assert mismo.ruta == primero.ruta
    assert segundo.ruta.name.endswith("_v2.xlsx")
    assert primero.ruta.read_bytes() == b"v1"


def test_limpieza_solo_toca_archivos_del_bot(tmp_path: Path) -> None:
    salida, capturas = tmp_path / "salida", tmp_path / "capturas"
    viejo = salida / "2026-01-05_2026-01-11" / "Asistencia_X_2026-01-05_al_2026-01-11.xlsx"
    ajeno = salida / "2026-01-05_2026-01-11" / "otro_archivo.xlsx"
    reciente = salida / "2026-10-12_2026-10-18" / "Asistencia_X_2026-10-12_al_2026-10-18.xlsx"
    captura_vieja = capturas / "abc_x.png"
    for ruta in (viejo, ajeno, reciente, captura_vieja):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(b"x")
    hace_200_dias = time.time() - 200 * 86400
    for ruta in (viejo, ajeno, captura_vieja):
        os.utime(ruta, (hace_200_dias, hace_200_dias))
    archivador = ArchivadorLocal(
        salida,
        [
            ReglaRetencion(salida, "*/Asistencia_*.xlsx", 180),
            ReglaRetencion(capturas, "*.png", 90),
            ReglaRetencion(tmp_path / "no_existe", "*", 1),
        ],
    )

    borrados = archivador.limpiar(datetime.now())

    assert borrados == 2
    assert not viejo.exists() and not captura_vieja.exists()
    assert ajeno.exists() and reciente.exists()


def test_limpieza_borra_carpetas_de_periodo_vacias(tmp_path: Path) -> None:
    salida = tmp_path / "salida"
    (salida / "2025-01-06_2025-01-12").mkdir(parents=True)
    ArchivadorLocal(salida, []).limpiar(datetime.now())

    assert not (salida / "2025-01-06_2025-01-12").exists()


# --- estado -------------------------------------------------------------------------------


def _ejecucion(modo: Modo, id_: str = "e1") -> Ejecucion:
    return Ejecucion(id_, datetime(2026, 10, 19, 7, tzinfo=None), modo, SEMANA, "0.1.0")


def test_idempotencia_solo_cuenta_produccion(tmp_path: Path) -> None:
    estado = EstadoSqlite(tmp_path / "estado.db")
    prueba = _ejecucion(Modo.PRUEBA, "p")
    estado.iniciar_ejecucion(prueba)
    estado.registrar_resultado(prueba, ResultadoGrupo("Fisio", EstadoGrupo.ENVIADO))
    assert not estado.ya_enviado(SEMANA, "Fisio")

    prod = _ejecucion(Modo.PRODUCCION, "q")
    estado.iniciar_ejecucion(prod)
    estado.registrar_resultado(prod, ResultadoGrupo("Fisio", EstadoGrupo.FALLIDO, error="x"))
    assert not estado.ya_enviado(SEMANA, "Fisio")

    estado.registrar_resultado(prod, ResultadoGrupo("Fisio", EstadoGrupo.ENVIADO))
    assert estado.ya_enviado(SEMANA, "Fisio")
    assert not estado.ya_enviado(Periodo(date(2026, 10, 19), date(2026, 10, 25)), "Fisio")


def test_ultimas_ejecuciones(tmp_path: Path) -> None:
    estado = EstadoSqlite(tmp_path / "estado.db")
    e = _ejecucion(Modo.DRY_RUN)
    estado.iniciar_ejecucion(e)
    r = ResultadoGrupo(
        "Fisio",
        EstadoGrupo.VALIDADO_SIN_ENVIO,
        filas=65,
        registros_consulta=65,
        destinatarios=("a@x.co",),
        advertencias=("ojo",),
        intentos=2,
        duracion_s=3.5,
    )
    e.resultados.append(r)
    estado.registrar_resultado(e, r)
    e.fin = e.inicio + timedelta(minutes=2)
    estado.finalizar_ejecucion(e)

    [leida] = estado.ultimas_ejecuciones(5)

    assert leida.id == "e1" and leida.modo is Modo.DRY_RUN and leida.fin == e.fin
    assert leida.resultados == [r]
    assert leida.codigo_salida == 0


# --- candado ------------------------------------------------------------------------------


def test_candado_impide_dos_ejecuciones(tmp_path: Path) -> None:
    ruta = tmp_path / "ejecucion.lock"
    with CandadoArchivo(ruta), pytest.raises(ErrorEjecucionEnCurso), CandadoArchivo(ruta):
        pass
    with CandadoArchivo(ruta):  # liberado al salir
        pass
