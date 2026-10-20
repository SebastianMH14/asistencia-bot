"""Histórico de Excel y retención.

La copia es byte a byte y se verifica con SHA-256. La limpieza solo toca archivos con
los patrones del bot dentro de sus propias carpetas; nunca Downloadcenter.
"""

import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from asistencia_bot.domain.errores import ErrorArchivo
from asistencia_bot.domain.modelos import ArchivoArchivado, Grupo, Periodo


def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 16), b""):
            h.update(bloque)
    return h.hexdigest()


@dataclass(frozen=True, slots=True)
class ReglaRetencion:
    carpeta: Path
    patron: str
    dias: int


class ArchivadorLocal:
    def __init__(self, salida: Path, reglas: list[ReglaRetencion]) -> None:
        self._salida = salida
        self._reglas = reglas

    def nombre_archivo(self, periodo: Periodo, grupo: Grupo) -> str:
        return f"Asistencia_{grupo.slug}_{periodo.desde.isoformat()}_al_{periodo.hasta.isoformat()}"

    def archivar(self, origen: Path, periodo: Periodo, grupo: Grupo) -> ArchivoArchivado:
        carpeta = self._salida / periodo.etiqueta()
        base = self.nombre_archivo(periodo, grupo)
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            sha_origen = sha256_de(origen)
            destino = carpeta / f"{base}.xlsx"
            version = 1
            # Un reenvío con --forzar puede traer otro contenido: se conserva el anterior.
            while destino.exists() and sha256_de(destino) != sha_origen:
                version += 1
                destino = carpeta / f"{base}_v{version}.xlsx"
            if not destino.exists():
                temporal = destino.with_suffix(".xlsx.tmp")
                shutil.copyfile(origen, temporal)
                os.replace(temporal, destino)
            sha_destino = sha256_de(destino)
        except OSError as e:
            raise ErrorArchivo(f"no se pudo copiar al histórico: {type(e).__name__}") from None
        if sha_destino != sha_origen:
            raise ErrorArchivo("la copia en el histórico no es idéntica al archivo exportado")
        return ArchivoArchivado(destino, sha_destino, destino.stat().st_size)

    def limpiar(self, ahora: datetime) -> int:
        borrados = 0
        for regla in self._reglas:
            raiz = regla.carpeta.resolve()
            if not raiz.exists():
                continue
            limite = (ahora - timedelta(days=regla.dias)).timestamp()
            for archivo in raiz.glob(regla.patron):
                if not archivo.is_file() or not archivo.resolve().is_relative_to(raiz):
                    continue
                if archivo.stat().st_mtime < limite:
                    archivo.unlink()
                    borrados += 1
        if self._salida.exists():
            for carpeta in self._salida.iterdir():
                if carpeta.is_dir() and not any(carpeta.iterdir()):
                    carpeta.rmdir()
        return borrados
