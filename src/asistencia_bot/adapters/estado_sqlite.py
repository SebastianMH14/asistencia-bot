"""Estado e idempotencia en SQLite (librería estándar).

Solo cuenta como "ya enviado" un envío exitoso en modo producción: las pruebas y los
dry-run no bloquean el envío real.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import date, datetime
from pathlib import Path

from asistencia_bot.domain.modelos import (
    Ejecucion,
    EstadoGrupo,
    Modo,
    Periodo,
    ResultadoGrupo,
)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ejecuciones (
    id             TEXT PRIMARY KEY,
    inicio         TEXT NOT NULL,
    fin            TEXT,
    modo           TEXT NOT NULL,
    periodo_desde  TEXT NOT NULL,
    periodo_hasta  TEXT NOT NULL,
    version_bot    TEXT NOT NULL,
    codigo_salida  INTEGER,
    error_fatal    TEXT,
    error_resumen  TEXT
);
CREATE TABLE IF NOT EXISTS resultados (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ejecucion_id        TEXT NOT NULL REFERENCES ejecuciones(id),
    periodo_desde       TEXT NOT NULL,
    periodo_hasta       TEXT NOT NULL,
    grupo               TEXT NOT NULL,
    modo                TEXT NOT NULL,
    estado              TEXT NOT NULL,
    filas               INTEGER,
    registros_consulta  INTEGER,
    destinatarios       TEXT NOT NULL,
    archivo             TEXT,
    sha256              TEXT,
    error               TEXT,
    advertencias        TEXT NOT NULL,
    intentos            INTEGER NOT NULL,
    duracion_s          REAL NOT NULL,
    fecha               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resultados_envio
    ON resultados (periodo_desde, periodo_hasta, grupo, modo, estado);
"""


class EstadoSqlite:
    def __init__(self, ruta: Path) -> None:
        self._ruta = ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._conexion() as con:
            con.executescript(ESQUEMA)

    @contextmanager
    def _conexion(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._ruta, timeout=10)) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            with con:  # transacción: commit o rollback
                yield con

    def iniciar_ejecucion(self, ejecucion: Ejecucion) -> None:
        with self._conexion() as con:
            con.execute(
                "INSERT INTO ejecuciones (id, inicio, modo, periodo_desde, periodo_hasta, "
                "version_bot) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ejecucion.id,
                    ejecucion.inicio.isoformat(),
                    ejecucion.modo.value,
                    ejecucion.periodo.desde.isoformat(),
                    ejecucion.periodo.hasta.isoformat(),
                    ejecucion.version_bot,
                ),
            )

    def registrar_resultado(self, ejecucion: Ejecucion, resultado: ResultadoGrupo) -> None:
        with self._conexion() as con:
            con.execute(
                "INSERT INTO resultados (ejecucion_id, periodo_desde, periodo_hasta, grupo, modo, "
                "estado, filas, registros_consulta, destinatarios, archivo, sha256, error, "
                "advertencias, intentos, duracion_s, fecha) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ejecucion.id,
                    ejecucion.periodo.desde.isoformat(),
                    ejecucion.periodo.hasta.isoformat(),
                    resultado.grupo,
                    ejecucion.modo.value,
                    resultado.estado.value,
                    resultado.filas,
                    resultado.registros_consulta,
                    json.dumps(list(resultado.destinatarios)),
                    resultado.archivo,
                    resultado.sha256,
                    resultado.error,
                    json.dumps(list(resultado.advertencias), ensure_ascii=False),
                    resultado.intentos,
                    resultado.duracion_s,
                    datetime.now().astimezone().isoformat(),
                ),
            )

    def finalizar_ejecucion(self, ejecucion: Ejecucion) -> None:
        with self._conexion() as con:
            con.execute(
                "UPDATE ejecuciones SET fin = ?, codigo_salida = ?, error_fatal = ?, "
                "error_resumen = ? WHERE id = ?",
                (
                    ejecucion.fin.isoformat() if ejecucion.fin else None,
                    ejecucion.codigo_salida,
                    ejecucion.error_fatal,
                    ejecucion.error_resumen,
                    ejecucion.id,
                ),
            )

    def ya_enviado(self, periodo: Periodo, grupo: str) -> bool:
        with self._conexion() as con:
            fila = con.execute(
                "SELECT 1 FROM resultados WHERE periodo_desde = ? AND periodo_hasta = ? "
                "AND grupo = ? AND modo = ? AND estado = ? LIMIT 1",
                (
                    periodo.desde.isoformat(),
                    periodo.hasta.isoformat(),
                    grupo,
                    Modo.PRODUCCION.value,
                    EstadoGrupo.ENVIADO.value,
                ),
            ).fetchone()
        return fila is not None

    def ultimas_ejecuciones(self, n: int) -> list[Ejecucion]:
        with self._conexion() as con:
            filas = con.execute(
                "SELECT * FROM ejecuciones ORDER BY inicio DESC LIMIT ?", (n,)
            ).fetchall()
            ejecuciones = []
            for f in filas:
                ejecucion = Ejecucion(
                    id=f["id"],
                    inicio=datetime.fromisoformat(f["inicio"]),
                    modo=Modo(f["modo"]),
                    periodo=Periodo(
                        date.fromisoformat(f["periodo_desde"]),
                        date.fromisoformat(f["periodo_hasta"]),
                    ),
                    version_bot=f["version_bot"],
                    fin=datetime.fromisoformat(f["fin"]) if f["fin"] else None,
                    error_fatal=f["error_fatal"],
                    error_resumen=f["error_resumen"],
                )
                for r in con.execute(
                    "SELECT * FROM resultados WHERE ejecucion_id = ? ORDER BY id", (f["id"],)
                ):
                    ejecucion.resultados.append(
                        ResultadoGrupo(
                            grupo=r["grupo"],
                            estado=EstadoGrupo(r["estado"]),
                            filas=r["filas"],
                            registros_consulta=r["registros_consulta"],
                            destinatarios=tuple(json.loads(r["destinatarios"])),
                            archivo=r["archivo"],
                            sha256=r["sha256"],
                            error=r["error"],
                            advertencias=tuple(json.loads(r["advertencias"])),
                            intentos=r["intentos"],
                            duracion_s=r["duracion_s"],
                        )
                    )
                ejecuciones.append(ejecucion)
        return ejecuciones
