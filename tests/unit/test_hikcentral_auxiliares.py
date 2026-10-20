"""Partes puras del adaptador de HikCentral (sin navegador)."""

import json
from datetime import date
from typing import Any

import pytest

from asistencia_bot.adapters.hikcentral import paginas
from asistencia_bot.adapters.hikcentral.selectores import PATRON_PERSONAS, _css_str
from asistencia_bot.adapters.hikcentral.sesion import resumir_error
from asistencia_bot.domain.errores import ErrorExtraccion
from asistencia_bot.domain.modelos import Periodo


class _Peticion:
    def __init__(self, cuerpo: dict[str, Any]) -> None:
        self.post_data = json.dumps(cuerpo)
        self.method = "POST"


class RespuestaFalsa:
    def __init__(self, datos: dict[str, Any], consulta: dict[str, Any] | None = None) -> None:
        self._datos = datos
        self.request = _Peticion(consulta or {})
        self.url = "https://127.0.0.1/ISAPI/Bumblebee/AttendancePlugin/V1/Record"

    def json(self) -> dict[str, Any]:
        return self._datos


def _registro(empleado: str, dia: str) -> dict[str, Any]:
    return {"BaseInfo": {"Date": dia, "PersonInfo": {"EmployeeID": empleado}}, "SignInTime": ""}


def test_clave_de_registro() -> None:
    assert paginas._clave(_registro(" E1 ", "2026-10-12")) == ("E1", date(2026, 10, 12))
    assert paginas._clave({"BaseInfo": {}}) is None
    assert paginas._clave(_registro("E1", "no-fecha")) is None


def test_periodo_consultado() -> None:
    consulta = {
        "RecordRequest": {
            "QueryInfo": {
                "BeginTime": "2026-10-12T00:00:00-05:00",
                "EndTime": "2026-10-18T23:59:59-05:00",
            }
        }
    }

    periodo = paginas._periodo_consultado(RespuestaFalsa({}, consulta))  # type: ignore[arg-type]

    assert periodo == Periodo(date(2026, 10, 12), date(2026, 10, 18))
    with pytest.raises(ErrorExtraccion):
        paginas._periodo_consultado(RespuestaFalsa({}, {}))  # type: ignore[arg-type]


def test_datos_de_la_respuesta() -> None:
    ok = RespuestaFalsa({"ResponseStatus": {"ErrorCode": 0, "Data": {"NextPage": 0}}})
    error = RespuestaFalsa({"ResponseStatus": {"ErrorCode": 17}})
    vacia = RespuestaFalsa({"ResponseStatus": {"ErrorCode": 0}})

    assert paginas._datos(ok) == {"NextPage": 0}  # type: ignore[arg-type]
    with pytest.raises(ErrorExtraccion, match="ErrorCode=17"):
        paginas._datos(error)  # type: ignore[arg-type]
    with pytest.raises(ErrorExtraccion, match="no trajo datos"):
        paginas._datos(vacia)  # type: ignore[arg-type]


def test_css_str_escapa_comillas() -> None:
    assert _css_str("Aux. Enfermería") == '"Aux. Enfermería"'
    assert _css_str('a"b') == '"a\\"b"'


def test_patron_personas() -> None:
    assert PATRON_PERSONAS.search("22 personas seleccionadas").group(1) == "22"  # type: ignore[union-attr]
    assert PATRON_PERSONAS.search("Personas seleccionadas") is None


def test_resumir_error_quita_call_log() -> None:
    error = TimeoutError("Locator.click: Timeout 30000ms exceeded.\nCall log:\n  <td>Ana</td>")

    assert resumir_error(error) == "TimeoutError: Locator.click: Timeout 30000ms exceeded."
    assert resumir_error(ValueError()) == "ValueError"


def test_resumir_error_incluye_solo_el_selector_esperado() -> None:
    error = TimeoutError(
        "Locator.click: Timeout 30000ms exceeded.\nCall log:\n"
        "  - waiting for locator(\"[role='tab'].el-tabs__item\").filter(visible=True).first\n"
        "    - locator resolved to <td>Ana Pérez</td>\n"
    )

    resumen = resumir_error(error)

    assert resumen.startswith("TimeoutError: Locator.click: Timeout 30000ms exceeded. (waiting for")
    assert "el-tabs__item" in resumen
    assert "Ana" not in resumen
