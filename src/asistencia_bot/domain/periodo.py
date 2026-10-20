"""Cálculo del periodo a reportar."""

from datetime import date, timedelta

from asistencia_bot.domain.modelos import Periodo


def semana_anterior(hoy: date) -> Periodo:
    """Lunes a domingo de la semana anterior a la semana de `hoy`.

    Una ejecución tardía (martes, o incluso domingo) sigue reportando la misma semana.
    Los festivos no cambian nada: la semana es calendario.
    """
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    desde = lunes_actual - timedelta(days=7)
    return Periodo(desde, desde + timedelta(days=6))
