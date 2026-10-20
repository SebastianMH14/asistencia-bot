"""Logs: JSON por línea con rotación (archivo) y formato legible (consola).

Nunca se registran nombres, cédulas, horarios ni contraseñas: solo eventos, grupos,
conteos, tiempos e identificadores de ejecución. Las trazas de excepción se reducen al
tipo y la primera línea, porque los errores de Playwright pueden traer HTML de la página.
"""

import json
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from asistencia_bot.adapters.logs import ARCHIVO_LOG

_ATRIBUTOS_ESTANDAR = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
}


def _extras(registro: logging.LogRecord) -> dict[str, Any]:
    return {
        k: v
        for k, v in vars(registro).items()
        if k not in _ATRIBUTOS_ESTANDAR and not k.startswith("_") and v is not None
    }


def _error_corto(registro: logging.LogRecord) -> str | None:
    if not registro.exc_info or registro.exc_info[1] is None:
        return None
    error = registro.exc_info[1]
    primera = str(error).split("Call log:")[0].strip().splitlines()
    return f"{type(error).__name__}: {primera[0][:200] if primera else ''}"


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        datos: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="seconds"),
            "nivel": record.levelname,
            "logger": record.name,
            "evento": record.getMessage(),
            **_extras(record),
        }
        if error := _error_corto(record):
            datos["excepcion"] = error
        return json.dumps(datos, ensure_ascii=False, default=str)


class FormatoConsola(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = " ".join(f"{k}={v}" for k, v in _extras(record).items())
        linea = f"{datetime.fromtimestamp(record.created):%H:%M:%S} {record.levelname:<7} "
        linea += record.getMessage() + (f"  [{extras}]" if extras else "")
        if error := _error_corto(record):
            linea += f"  ({error})"
        return linea


def configurar_logging(carpeta: Path, nivel: int = logging.INFO, consola: bool = True) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    raiz = logging.getLogger()
    for manejador in list(raiz.handlers):
        raiz.removeHandler(manejador)
    raiz.setLevel(nivel)
    archivo = RotatingFileHandler(
        carpeta / ARCHIVO_LOG, maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    archivo.setFormatter(FormatoJson())
    raiz.addHandler(archivo)
    if consola:
        salida = logging.StreamHandler(sys.stderr)
        salida.setFormatter(FormatoConsola())
        raiz.addHandler(salida)
    for ruidoso in ("asyncio", "urllib3", "playwright"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
