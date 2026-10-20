from dataclasses import replace
from datetime import date

from asistencia_bot.domain.modelos import ConsultaInterfaz, Grupo, MetadatosReporte, Periodo
from asistencia_bot.domain.validacion import (
    ENCABEZADOS_REQUERIDOS,
    departamento_corresponde,
    validar_reporte,
)

SEMANA = Periodo(date(2026, 10, 12), date(2026, 10, 18))
FISIO = Grupo("Fisioterapeutas", "Fisioterapeutas")
CLAVES = frozenset((f"E{p}", date(2026, 10, 12 + d)) for p in range(13) for d in range(5))


def _meta(**cambios: object) -> MetadatosReporte:
    base = MetadatosReporte(
        hoja="Sheet1",
        titulo="Registros de entradas y salidas",
        periodo_texto="2026-10-12 - 2026-10-18",
        encabezados=(*ENCABEZADOS_REQUERIDOS, "Semana", "Duración"),
        departamentos=frozenset({"General>Fisioterapeutas"}),
        filas=65,
        claves=CLAVES,
    )
    return replace(base, **cambios)  # type: ignore[arg-type]


def _consulta(
    registros: int = 65, paginas: int = 1, claves: frozenset[tuple[str, date]] = CLAVES
) -> ConsultaInterfaz:
    return ConsultaInterfaz(paginas, registros, SEMANA, claves)


def test_valido_con_una_pagina() -> None:
    r = validar_reporte(_meta(), SEMANA, FISIO, _consulta())

    assert r.valido
    assert r.advertencias == ()


def test_periodo_distinto() -> None:
    r = validar_reporte(_meta(periodo_texto="2026-10-05 - 2026-10-11"), SEMANA, FISIO, _consulta())

    assert not r.valido
    assert "periodo del Excel" in r.errores[0]


def test_departamento_mezclado() -> None:
    meta = _meta(departamentos=frozenset({"General>Fisioterapeutas", "General>Medicos"}))

    r = validar_reporte(meta, SEMANA, FISIO, _consulta())

    assert not r.valido
    assert "General>Medicos" in r.errores[0]


def test_encabezados_faltantes() -> None:
    r = validar_reporte(_meta(encabezados=("Nombre", "Fecha")), SEMANA, FISIO, _consulta())

    assert any("faltan encabezados" in e and "Departamento" in e for e in r.errores)


def test_una_pagina_exige_igualdad() -> None:
    r = validar_reporte(_meta(filas=64), SEMANA, FISIO, _consulta(65))

    assert not r.valido
    assert "64 filas" in r.errores[0]


def test_varias_paginas_contencion_y_advertencia() -> None:
    """ADR-0005: el Excel puede traer más que la suma de páginas, nunca menos ni otras claves."""
    vistas = frozenset(list(CLAVES)[:60])

    r = validar_reporte(_meta(), SEMANA, FISIO, _consulta(60, paginas=2, claves=vistas))

    assert r.valido
    assert "paginación de HikCentral" in r.advertencias[0]


def test_varias_paginas_detecta_excel_truncado() -> None:
    extra = frozenset({("E999", date(2026, 10, 13))})

    r = validar_reporte(_meta(), SEMANA, FISIO, _consulta(66, paginas=2, claves=CLAVES | extra))

    assert not r.valido
    assert any("no están en el Excel" in e for e in r.errores)
    assert any("menos que los 66" in e for e in r.errores)


def test_sin_registros_es_valido() -> None:
    r = validar_reporte(
        _meta(filas=0, claves=frozenset(), departamentos=frozenset()),
        SEMANA,
        FISIO,
        _consulta(0, claves=frozenset()),
    )

    assert r.valido


def test_fechas_fuera_del_periodo_y_sin_fecha() -> None:
    claves = CLAVES | {("E1", date(2026, 10, 20))}

    r = validar_reporte(_meta(claves=claves, filas_sin_fecha=2), SEMANA, FISIO, None)

    assert any("fuera del periodo" in e for e in r.errores)
    assert any("2 filas no tienen una fecha legible" in e for e in r.errores)


def test_sin_consulta_advierte_multiplo_de_100() -> None:
    r = validar_reporte(_meta(filas=200), SEMANA, FISIO, None)

    assert r.valido
    assert "múltiplo de 100" in r.advertencias[0]


def test_departamento_corresponde() -> None:
    assert departamento_corresponde("General>Fisioterapeutas", FISIO)
    assert departamento_corresponde("Fisioterapeutas", FISIO)
    assert not departamento_corresponde("General>Otros Fisioterapeutas", FISIO)
