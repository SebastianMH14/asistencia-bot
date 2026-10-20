"""Genera Excel SINTÉTICOS con la estructura del reporte de HikCentral.

Ningún dato es real: nombres, IDs y horarios se inventan. Estructura observada:
filas 1-3 vacías, 4 título, 5 hora de exportación, 6 operador, 7 "Periodo: …",
8 encabezados, 9+ datos (ver DISCOVERY.md §2.3 del encargo).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

ENCABEZADOS = (
    "Nombre",
    "Apellido",
    "ID",
    "Departamento",
    "Fecha",
    "Semana",
    "Periodo de tiempo",
    "Hora de registro de entrada",
    "Salida a",
    "Duración",
    "Duración total",
)
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


@dataclass
class FilaSintetica:
    id_empleado: str
    fecha: date
    departamento: str = "General>Fisioterapeutas"
    entrada: str = "07:00:00"
    salida: str = "15:00:00"


@dataclass
class ExcelSintetico:
    periodo: str = "2026-10-12 - 2026-10-18"
    filas: list[FilaSintetica] = field(default_factory=list)
    encabezados: tuple[str, ...] = ENCABEZADOS
    filas_vacias_iniciales: int = 3
    hoja: str = "Sheet1"

    def guardar(self, ruta: Path) -> Path:
        libro = Workbook()
        hoja = libro.active
        assert hoja is not None
        hoja.title = self.hoja
        for _ in range(self.filas_vacias_iniciales):
            hoja.append([])
        hoja.append(["Registros de entradas y salidas"])
        hoja.append(["Hora de exportación: 2026-10-19 07:00"])
        hoja.append(["Operador: admin"])
        hoja.append([f"Periodo: {self.periodo}"])
        hoja.append(list(self.encabezados))
        for i, f in enumerate(self.filas):
            valores = {
                "Nombre": f"Persona{i}",
                "Apellido": "Sintética",
                "ID": f.id_empleado,
                "Departamento": f.departamento,
                "Fecha": f.fecha.isoformat(),
                "Semana": DIAS[f.fecha.weekday()],
                "Periodo de tiempo": "Turno",
                "Hora de registro de entrada": f.entrada,
                "Salida a": f.salida,
                "Duración": "08:00",
                "Duración total": "08:00",
            }
            hoja.append([valores.get(e, "") for e in self.encabezados])
        ruta.parent.mkdir(parents=True, exist_ok=True)
        libro.save(ruta)
        return ruta


def filas_semana(
    personas: int,
    desde: date = date(2026, 10, 12),
    dias: int = 5,
    departamento: str = "General>Fisioterapeutas",
) -> list[FilaSintetica]:
    return [
        FilaSintetica(f"E{p:03d}", desde + timedelta(days=d), departamento)
        for p in range(personas)
        for d in range(dias)
    ]
