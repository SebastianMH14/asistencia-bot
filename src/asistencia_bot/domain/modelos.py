"""Modelos del dominio (inmutables salvo `Ejecucion`, que se va completando)."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path

REPORTE_HIK = "Registros de entradas y salidas"


class Modo(StrEnum):
    PRODUCCION = "produccion"
    PRUEBA = "prueba"
    DRY_RUN = "dry_run"

    @property
    def envia_correos(self) -> bool:
        return self is not Modo.DRY_RUN


class EstadoGrupo(StrEnum):
    ENVIADO = "ENVIADO"
    VALIDADO_SIN_ENVIO = "VALIDADO_SIN_ENVIO"
    OMITIDO_SIN_REGISTROS = "OMITIDO_SIN_REGISTROS"
    OMITIDO_YA_ENVIADO = "OMITIDO_YA_ENVIADO"
    FALLIDO = "FALLIDO"


class PoliticaSinRegistros(StrEnum):
    OMITIR_Y_REPORTAR = "omitir_y_reportar"
    ENVIAR_AVISO = "enviar_aviso_sin_registros"


@dataclass(frozen=True, slots=True)
class Periodo:
    """Rango de fechas cerrado [desde, hasta]."""

    desde: date
    hasta: date

    def __post_init__(self) -> None:
        if self.hasta < self.desde:
            raise ValueError(f"periodo inválido: {self.desde} > {self.hasta}")

    def contiene(self, dia: date) -> bool:
        return self.desde <= dia <= self.hasta

    def dias(self) -> tuple[date, ...]:
        return tuple(
            self.desde + timedelta(days=i) for i in range((self.hasta - self.desde).days + 1)
        )

    def etiqueta(self) -> str:
        """Nombre de carpeta del histórico: ``2026-10-12_2026-10-18``."""
        return f"{self.desde.isoformat()}_{self.hasta.isoformat()}"

    def texto_hik(self) -> str:
        """Valor de la fila "Periodo:" del Excel de HikCentral: ``2026-10-12 - 2026-10-18``."""
        return f"{self.desde.isoformat()} - {self.hasta.isoformat()}"

    def texto_asunto(self) -> str:
        """Para el asunto: ``12/10 al 18/10/2026``."""
        return f"{self.desde:%d/%m} al {self.hasta:%d/%m/%Y}"

    def nombre_archivo_hik(self) -> str:
        """Nombre con el que HikCentral guarda la exportación."""
        return f"{REPORTE_HIK}_{self.desde.isoformat()}_{self.hasta.isoformat()}.xlsx"


@dataclass(frozen=True, slots=True)
class Jefe:
    nombre: str
    correo: str


@dataclass(frozen=True, slots=True)
class Grupo:
    """Departamento de HikCentral que recibe un reporte."""

    nombre: str
    departamento_hik: str
    jefe: Jefe | None = None
    cc: tuple[str, ...] = ()
    activo: bool = True

    @property
    def slug(self) -> str:
        """Nombre ASCII para archivos: ``Aux. Enfermería`` → ``Aux_Enfermeria``."""
        sin_tildes = unicodedata.normalize("NFKD", self.nombre).encode("ascii", "ignore").decode()
        return re.sub(r"[^A-Za-z0-9]+", "_", sin_tildes).strip("_") or "grupo"

    @property
    def destinatarios(self) -> tuple[str, ...]:
        return ((self.jefe.correo,) if self.jefe else ()) + self.cc


ClaveRegistro = tuple[str, date]
"""(ID de empleado, fecha). Dato personal: solo en memoria, nunca en logs ni en disco."""


def nombre_entregable(grupo: Grupo, periodo: Periodo) -> str:
    """``Asistencia_<Grupo>_<desde>_al_<hasta>.xlsx``: nombre del adjunto y base del histórico."""
    return (
        f"Asistencia_{grupo.slug}_{periodo.desde.isoformat()}_al_{periodo.hasta.isoformat()}.xlsx"
    )


@dataclass(frozen=True, slots=True)
class ConsultaInterfaz:
    """Lo que el extractor vio al recorrer la consulta paginada de la tabla."""

    paginas: int
    registros: int
    periodo_consultado: Periodo
    claves: frozenset[ClaveRegistro] = field(default=frozenset(), repr=False)

    @property
    def una_pagina(self) -> bool:
        return self.paginas <= 1


@dataclass(frozen=True, slots=True)
class MetadatosReporte:
    """Estructura del Excel exportado. Sin nombres; `claves` solo en memoria."""

    hoja: str
    titulo: str
    periodo_texto: str
    encabezados: tuple[str, ...]
    departamentos: frozenset[str]
    filas: int
    claves: frozenset[ClaveRegistro] = field(default=frozenset(), repr=False)
    filas_sin_fecha: int = 0

    @property
    def fechas(self) -> frozenset[date]:
        """Días con al menos un registro: un agregado sin IDs, que sí puede salir de memoria."""
        return frozenset(dia for _, dia in self.claves)


@dataclass(frozen=True, slots=True)
class ReporteExportado:
    grupo: str
    ruta: Path
    tamano_bytes: int
    consulta: ConsultaInterfaz | None


@dataclass(frozen=True, slots=True)
class ArchivoArchivado:
    ruta: Path
    sha256: str
    tamano_bytes: int


@dataclass(frozen=True, slots=True)
class Adjunto:
    nombre: str
    tipo_mime: str
    contenido: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class Correo:
    para: tuple[str, ...]
    asunto: str
    texto: str
    html: str
    cc: tuple[str, ...] = ()
    adjuntos: tuple[Adjunto, ...] = ()


@dataclass(frozen=True, slots=True)
class ResultadoGrupo:
    grupo: str
    estado: EstadoGrupo
    filas: int | None = None
    registros_consulta: int | None = None
    destinatarios: tuple[str, ...] = ()
    archivo: str | None = None
    sha256: str | None = None
    error: str | None = None
    advertencias: tuple[str, ...] = ()
    intentos: int = 0
    duracion_s: float = 0.0
    evidencias: tuple[Path, ...] = ()
    fechas_con_registros: frozenset[date] | None = None  # None: el Excel no se leyó o no era válido

    @property
    def fallido(self) -> bool:
        return self.estado is EstadoGrupo.FALLIDO


@dataclass(slots=True)
class Ejecucion:
    id: str
    inicio: datetime
    modo: Modo
    periodo: Periodo
    version_bot: str
    resultados: list[ResultadoGrupo] = field(default_factory=list)
    fin: datetime | None = None
    error_fatal: str | None = None
    error_resumen: str | None = None

    @property
    def codigo_salida(self) -> int:
        """0 todo OK, 1 fallos parciales (o no se pudo avisar al administrador), 2 fatal."""
        if self.error_fatal:
            return 2
        if self.error_resumen or any(r.fallido for r in self.resultados):
            return 1
        return 0

    @property
    def duracion_s(self) -> float:
        return (self.fin - self.inicio).total_seconds() if self.fin else 0.0

    @property
    def dias_sin_registros(self) -> tuple[date, ...]:
        """Días de lunes a sábado sin registros en ninguno de los grupos que se leyeron.

        Suele ser un festivo o que HikCentral no recibió marcaciones (lector caído). El bot no
        puede distinguirlos: solo avisa al administrador y no frena el envío.
        """
        leidas = [
            r.fechas_con_registros for r in self.resultados if r.fechas_con_registros is not None
        ]
        if not leidas:
            return ()
        con_registros = {dia for fechas in leidas for dia in fechas}
        return tuple(
            dia for dia in self.periodo.dias() if dia.weekday() != 6 and dia not in con_registros
        )
