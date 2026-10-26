from datetime import date, datetime

import pytest

from asistencia_bot.domain.modelos import (
    Ejecucion,
    EstadoGrupo,
    Grupo,
    Jefe,
    MetadatosReporte,
    Modo,
    Periodo,
    ResultadoGrupo,
)
from asistencia_bot.domain.periodo import semana_anterior

SEMANA = Periodo(date(2026, 10, 12), date(2026, 10, 18))


@pytest.mark.parametrize(
    ("hoy", "desde", "hasta"),
    [
        (date(2026, 10, 19), date(2026, 10, 12), date(2026, 10, 18)),  # lunes normal
        (date(2026, 10, 20), date(2026, 10, 12), date(2026, 10, 18)),  # martes: ejecución tardía
        (date(2026, 10, 25), date(2026, 10, 12), date(2026, 10, 18)),  # domingo: muy tardía
        (date(2027, 1, 4), date(2026, 12, 28), date(2027, 1, 3)),  # cambio de año
        (date(2026, 1, 5), date(2025, 12, 29), date(2026, 1, 4)),  # cambio de año (otro)
        (date(2026, 11, 16), date(2026, 11, 9), date(2026, 11, 15)),  # lunes festivo (Colombia)
        (date(2028, 3, 6), date(2028, 2, 28), date(2028, 3, 5)),  # año bisiesto
    ],
)
def test_semana_anterior(hoy: date, desde: date, hasta: date) -> None:
    periodo = semana_anterior(hoy)

    assert (periodo.desde, periodo.hasta) == (desde, hasta)
    assert periodo.desde.weekday() == 0
    assert (periodo.hasta - periodo.desde).days == 6


def test_textos_del_periodo() -> None:
    assert SEMANA.etiqueta() == "2026-10-12_2026-10-18"
    assert SEMANA.texto_hik() == "2026-10-12 - 2026-10-18"
    assert SEMANA.texto_asunto() == "12/10 al 18/10/2026"
    assert SEMANA.nombre_archivo_hik() == (
        "Registros de entradas y salidas_2026-10-12_2026-10-18.xlsx"
    )
    assert SEMANA.contiene(date(2026, 10, 15))
    assert not SEMANA.contiene(date(2026, 10, 19))


def test_periodo_invalido() -> None:
    with pytest.raises(ValueError, match="periodo inválido"):
        Periodo(date(2026, 10, 18), date(2026, 10, 12))


def test_slug_y_destinatarios_del_grupo() -> None:
    grupo = Grupo("Aux. Enfermería", "Aux. Enfermería", Jefe("J", "j@x.co"), ("c@x.co",))

    assert grupo.slug == "Aux_Enfermeria"
    assert grupo.destinatarios == ("j@x.co", "c@x.co")
    assert Grupo("Médicos", "Medicos").slug == "Medicos"
    assert Grupo("¿?", "x").slug == "grupo"
    assert Grupo("Sin jefe", "x").destinatarios == ()


def _ejecucion(*estados: EstadoGrupo, fatal: str | None = None) -> Ejecucion:
    e = Ejecucion("id", datetime(2026, 10, 19, 7), Modo.PRUEBA, SEMANA, "0.1.0", error_fatal=fatal)
    e.resultados = [ResultadoGrupo(f"g{i}", s) for i, s in enumerate(estados)]
    return e


def test_codigo_de_salida() -> None:
    assert _ejecucion(EstadoGrupo.ENVIADO, EstadoGrupo.OMITIDO_YA_ENVIADO).codigo_salida == 0
    assert _ejecucion(EstadoGrupo.ENVIADO, EstadoGrupo.FALLIDO).codigo_salida == 1
    assert _ejecucion(EstadoGrupo.FALLIDO).codigo_salida == 1
    assert _ejecucion(EstadoGrupo.ENVIADO, fatal="x").codigo_salida == 2
    sin_resumen = _ejecucion(EstadoGrupo.ENVIADO)
    sin_resumen.error_resumen = "smtp caído"
    assert sin_resumen.codigo_salida == 1


def test_duracion() -> None:
    e = _ejecucion()
    assert e.duracion_s == 0.0
    e.fin = datetime(2026, 10, 19, 7, 2, 30)
    assert e.duracion_s == 150.0


def test_modo_envia_correos() -> None:
    assert Modo.PRODUCCION.envia_correos and Modo.PRUEBA.envia_correos
    assert not Modo.DRY_RUN.envia_correos


def test_dias_y_fechas_del_reporte() -> None:
    meta = MetadatosReporte(
        "h", "t", "p", (), frozenset(), 3, claves=frozenset({("1", date(2026, 10, 12))})
    )

    assert SEMANA.dias()[0] == date(2026, 10, 12) and len(SEMANA.dias()) == 7
    assert meta.fechas == frozenset({date(2026, 10, 12)})


def test_dias_sin_registros() -> None:
    e = _ejecucion()
    assert e.dias_sin_registros == ()  # ningún Excel leído: no hay nada que afirmar

    e.resultados = [
        ResultadoGrupo(
            "a",
            EstadoGrupo.ENVIADO,
            fechas_con_registros=frozenset({date(2026, 10, 12), date(2026, 10, 13)}),
        ),
        ResultadoGrupo(
            "b",
            EstadoGrupo.ENVIADO,
            fechas_con_registros=frozenset({date(2026, 10, 13), date(2026, 10, 16)}),
        ),
        ResultadoGrupo("c", EstadoGrupo.FALLIDO),  # sin leer: no cuenta
    ]

    # Miércoles 14, jueves 15 y sábado 17; el domingo 18 no se revisa.
    assert e.dias_sin_registros == (date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 17))


def test_dias_sin_registros_semana_vacia() -> None:
    e = _ejecucion()
    e.resultados = [
        ResultadoGrupo("a", EstadoGrupo.OMITIDO_SIN_REGISTROS, fechas_con_registros=frozenset())
    ]

    assert len(e.dias_sin_registros) == 6


def test_nombre_entregable() -> None:
    from asistencia_bot.domain.modelos import nombre_entregable

    grupo = Grupo("Aux. Enfermería", "Aux. Enfermería")

    assert nombre_entregable(grupo, SEMANA) == (
        "Asistencia_Aux_Enfermeria_2026-10-12_al_2026-10-18.xlsx"
    )
