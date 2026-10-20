from datetime import date
from pathlib import Path

import pytest

from asistencia_bot.adapters.excel_validador import InspectorExcel
from asistencia_bot.domain.errores import ErrorLectura
from fixtures.excel_sintetico import ENCABEZADOS, ExcelSintetico, FilaSintetica, filas_semana

inspector = InspectorExcel()


def test_lee_estructura_ok(tmp_path: Path) -> None:
    ruta = ExcelSintetico(filas=filas_semana(13)).guardar(tmp_path / "ok.xlsx")

    meta = inspector.leer_metadatos(ruta)

    assert meta.periodo_texto == "2026-10-12 - 2026-10-18"
    assert meta.titulo == "Registros de entradas y salidas"
    assert meta.encabezados == ENCABEZADOS
    assert meta.departamentos == {"General>Fisioterapeutas"}
    assert meta.filas == 65
    assert len(meta.claves) == 65
    assert ("E000", date(2026, 10, 12)) in meta.claves
    assert meta.filas_sin_fecha == 0


def test_no_depende_de_numeros_de_fila(tmp_path: Path) -> None:
    """Encabezados movidos (más filas vacías y columnas en otro orden)."""
    movidos = (*reversed(ENCABEZADOS),)
    ruta = ExcelSintetico(
        filas=filas_semana(2), encabezados=movidos, filas_vacias_iniciales=6
    ).guardar(tmp_path / "movido.xlsx")

    meta = inspector.leer_metadatos(ruta)

    assert meta.filas == 10
    assert meta.periodo_texto == "2026-10-12 - 2026-10-18"
    assert set(meta.encabezados) == set(ENCABEZADOS)
    assert len(meta.claves) == 10


def test_sin_filas(tmp_path: Path) -> None:
    meta = inspector.leer_metadatos(ExcelSintetico().guardar(tmp_path / "vacio.xlsx"))

    assert meta.filas == 0
    assert meta.departamentos == frozenset()


def test_departamento_mezclado(tmp_path: Path) -> None:
    filas = [
        FilaSintetica("E1", date(2026, 10, 12)),
        FilaSintetica("E2", date(2026, 10, 13), departamento="General>Medicos"),
    ]
    ruta = ExcelSintetico(filas=filas).guardar(tmp_path / "mezcla.xlsx")
    meta = inspector.leer_metadatos(ruta)

    assert meta.departamentos == {"General>Fisioterapeutas", "General>Medicos"}


def test_sin_encabezados(tmp_path: Path) -> None:
    ruta = ExcelSintetico(encabezados=("Otra", "Cosa")).guardar(tmp_path / "raro.xlsx")

    meta = inspector.leer_metadatos(ruta)

    assert meta.encabezados == ()
    assert meta.filas == 0


def test_archivo_corrupto(tmp_path: Path) -> None:
    ruta = tmp_path / "roto.xlsx"
    ruta.write_bytes(b"no es un xlsx")

    with pytest.raises(ErrorLectura, match=r"roto\.xlsx"):
        inspector.leer_metadatos(ruta)


def test_repr_no_expone_claves(tmp_path: Path) -> None:
    meta = inspector.leer_metadatos(
        ExcelSintetico(filas=filas_semana(1)).guardar(tmp_path / "x.xlsx")
    )

    assert "E000" not in repr(meta)
