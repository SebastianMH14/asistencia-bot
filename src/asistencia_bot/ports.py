"""Puertos del hexágono: lo que el dominio y los servicios necesitan del exterior.

Los adaptadores concretos (keyring, Playwright, SMTP, SQLite, openpyxl, jinja2) viven en
``adapters/`` y se conectan en ``bootstrap.py``.
"""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from asistencia_bot.domain.modelos import (
    ArchivoArchivado,
    Correo,
    Ejecucion,
    Grupo,
    MetadatosReporte,
    Periodo,
    ReporteExportado,
    ResultadoGrupo,
)


class Reloj(Protocol):
    def ahora(self) -> datetime:
        """Fecha y hora con zona (America/Bogota)."""
        ...


class AlmacenCredenciales(Protocol):
    """Guarda y recupera secretos por sistema (``hikcentral``, ``smtp``) y usuario."""

    def obtener(self, sistema: str, usuario: str) -> str | None:
        """Devuelve el secreto o ``None`` si no hay ninguno guardado."""
        ...

    def guardar(self, sistema: str, usuario: str, secreto: str) -> None:
        """Crea o reemplaza el secreto."""
        ...

    def borrar(self, sistema: str, usuario: str) -> bool:
        """Elimina el secreto; devuelve ``False`` si no existía."""
        ...


class VerificadorEntorno(Protocol):
    def problemas(self) -> list[str]:
        """Precondiciones que fallan (HikCentral, HCWebControl, carpeta, credenciales)."""
        ...


class ExtractorAsistencia(Protocol):
    """Una sesión de HikCentral durante una ejecución."""

    def abrir(self) -> None:
        """Abre el navegador e inicia sesión. Lanza ErrorLogin o ErrorEntorno."""
        ...

    def exportar(self, grupo: Grupo, periodo: Periodo) -> ReporteExportado:
        """Exporta el reporte del grupo para el periodo. Lanza ErrorGrupo si falla."""
        ...

    def guardar_evidencia(self, etiqueta: str) -> tuple[Path, ...]:
        """Captura de pantalla (y trace si existe) del último fallo. Archivos sensibles."""
        ...

    def cerrar(self) -> None:
        """Cierra sesión y el navegador. No lanza excepciones."""
        ...


class InspectorReporte(Protocol):
    def leer_metadatos(self, ruta: Path) -> MetadatosReporte: ...


class Archivador(Protocol):
    def archivar(self, origen: Path, periodo: Periodo, grupo: Grupo) -> ArchivoArchivado:
        """Copia byte a byte al histórico y verifica el SHA-256."""
        ...

    def limpiar(self, ahora: datetime) -> int:
        """Aplica la retención solo a archivos creados por el bot. Devuelve cuántos borró."""
        ...


class Notificador(Protocol):
    def enviar(self, correo: Correo) -> None:
        """Envía o lanza ErrorNotificacion tras los reintentos."""
        ...


class RenderizadorCorreos(Protocol):
    def correo_jefe(
        self,
        grupo: Grupo,
        periodo: Periodo,
        archivo: ArchivoArchivado,
        nombre_adjunto: str,
    ) -> Correo: ...

    def correo_sin_registros(self, grupo: Grupo, periodo: Periodo) -> Correo: ...

    def correo_resumen(
        self, ejecucion: Ejecucion, para: str, adjuntos: Sequence[Path]
    ) -> Correo: ...

    def redirigir_a_prueba(self, correo: Correo, administrador: str) -> Correo:
        """Copia del correo dirigida solo al administrador, marcada [PRUEBA]."""
        ...


class RepositorioEstado(Protocol):
    def iniciar_ejecucion(self, ejecucion: Ejecucion) -> None: ...

    def registrar_resultado(self, ejecucion: Ejecucion, resultado: ResultadoGrupo) -> None: ...

    def finalizar_ejecucion(self, ejecucion: Ejecucion) -> None: ...

    def ya_enviado(self, periodo: Periodo, grupo: str) -> bool:
        """True si hay un envío de producción exitoso de ese grupo para ese periodo."""
        ...

    def ultimas_ejecuciones(self, n: int) -> list[Ejecucion]: ...
