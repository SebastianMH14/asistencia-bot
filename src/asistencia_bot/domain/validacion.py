"""Reglas de validación del Excel exportado (ver ADR-0005 para la regla de filas).

Los mensajes solo llevan conteos, fechas, nombres de departamento y encabezados.
"""

from dataclasses import dataclass

from asistencia_bot.domain.modelos import ConsultaInterfaz, Grupo, MetadatosReporte, Periodo

ENCABEZADOS_REQUERIDOS: tuple[str, ...] = (
    "Nombre",
    "Apellido",
    "ID",
    "Departamento",
    "Fecha",
    "Hora de registro de entrada",
    "Salida a",
)


@dataclass(frozen=True, slots=True)
class ResultadoValidacion:
    errores: tuple[str, ...] = ()
    advertencias: tuple[str, ...] = ()

    @property
    def valido(self) -> bool:
        return not self.errores


def departamento_corresponde(departamento: str, grupo: Grupo) -> bool:
    """`General>Fisioterapeutas` corresponde al grupo con departamento_hik `Fisioterapeutas`."""
    return departamento == grupo.departamento_hik or departamento.endswith(
        f">{grupo.departamento_hik}"
    )


def validar_reporte(
    meta: MetadatosReporte,
    periodo: Periodo,
    grupo: Grupo,
    consulta: ConsultaInterfaz | None,
) -> ResultadoValidacion:
    errores: list[str] = []
    advertencias: list[str] = []

    if meta.periodo_texto != periodo.texto_hik():
        errores.append(
            f"el periodo del Excel ({meta.periodo_texto!r}) no es el esperado "
            f"({periodo.texto_hik()!r})"
        )

    faltantes = [e for e in ENCABEZADOS_REQUERIDOS if e not in meta.encabezados]
    if faltantes:
        errores.append(f"faltan encabezados: {', '.join(faltantes)}")

    ajenos = sorted(d for d in meta.departamentos if not departamento_corresponde(d, grupo))
    if ajenos:
        errores.append(
            f"el Excel trae departamentos que no son de '{grupo.nombre}': {', '.join(ajenos)}"
        )

    fuera = sum(1 for _, dia in meta.claves if not periodo.contiene(dia))
    if fuera:
        errores.append(f"{fuera} filas tienen fecha fuera del periodo")
    if meta.filas_sin_fecha:
        errores.append(f"{meta.filas_sin_fecha} filas no tienen una fecha legible")

    if consulta is not None:
        errores.extend(_validar_filas(meta, consulta, advertencias))
    elif meta.filas and meta.filas % 100 == 0:
        advertencias.append(
            f"el Excel tiene {meta.filas} filas (múltiplo de 100) y no se pudo comparar "
            "con la consulta de la interfaz"
        )

    return ResultadoValidacion(tuple(errores), tuple(advertencias))


def _validar_filas(
    meta: MetadatosReporte, consulta: ConsultaInterfaz, advertencias: list[str]
) -> list[str]:
    """Regla de ADR-0005: una página → igualdad; varias → contención de claves y ≥."""
    if consulta.una_pagina:
        if meta.filas != consulta.registros:
            return [
                f"el Excel tiene {meta.filas} filas y la consulta de la interfaz "
                f"{consulta.registros} registros"
            ]
        return []

    errores: list[str] = []
    faltan = len(consulta.claves - meta.claves)
    if faltan:
        errores.append(
            f"{faltan} registros vistos en la consulta no están en el Excel (posible exportación "
            "truncada)"
        )
    if meta.filas < consulta.registros:
        errores.append(
            f"el Excel tiene {meta.filas} filas, menos que los {consulta.registros} registros "
            f"de la consulta ({consulta.paginas} páginas)"
        )
    elif meta.filas > consulta.registros:
        advertencias.append(
            f"el Excel tiene {meta.filas} filas y la consulta paginada mostró "
            f"{consulta.registros}: diferencia esperable por la paginación de HikCentral "
            "(ADR-0005)"
        )
    return errores
