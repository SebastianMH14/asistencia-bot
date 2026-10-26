"""Construcción de correos con jinja2 (HTML con alternativa en texto plano)."""

import mimetypes
import socket
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from markupsafe import escape

from asistencia_bot.domain.modelos import (
    Adjunto,
    ArchivoArchivado,
    Correo,
    Ejecucion,
    EstadoGrupo,
    Grupo,
    Modo,
    Periodo,
    ResultadoGrupo,
)
from asistencia_bot.domain.vigilancia import EstadoLector

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GUION = chr(0x2013)  # raya (en dash) del asunto acordado con el cliente
COLORES = {
    EstadoGrupo.ENVIADO: "#2e7d32",
    EstadoGrupo.VALIDADO_SIN_ENVIO: "#2e7d32",
    EstadoGrupo.OMITIDO_YA_ENVIADO: "#555555",
    EstadoGrupo.OMITIDO_SIN_REGISTROS: "#8a6d00",
    EstadoGrupo.FALLIDO: "#c62828",
}
# Sin depender del locale de Windows.
DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _fecha(dia: datetime | None) -> str:
    return f"{dia:%Y-%m-%d %H:%M:%S}" if dia else "—"


def _dias(dias: Sequence[date]) -> str:
    """``miércoles 21/10, jueves 22/10``."""
    return ", ".join(f"{DIAS_SEMANA[d.weekday()]} {d:%d/%m}" for d in dias)


def _duracion(segundos: float) -> str:
    minutos, seg = divmod(round(segundos), 60)
    return f"{minutos} min {seg:02d} s" if minutos else f"{seg} s"


def _mime(ruta: Path) -> str:
    return mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"


class RenderizadorJinja:
    def __init__(self, version: str) -> None:
        self._version = version
        self._env = Environment(
            loader=PackageLoader("asistencia_bot", "templates"),
            autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _render(self, base: str, contexto: dict[str, Any]) -> tuple[str, str]:
        texto = self._env.get_template(f"{base}.txt.j2").render(contexto)
        html = self._env.get_template(f"{base}.html.j2").render(contexto)
        return texto, html

    def _contexto_periodo(self, grupo: Grupo, periodo: Periodo) -> dict[str, Any]:
        return {
            "grupo": grupo.nombre,
            "desde": f"{periodo.desde:%d/%m/%Y}",
            "hasta": f"{periodo.hasta:%d/%m/%Y}",
        }

    def correo_jefe(
        self,
        grupo: Grupo,
        periodo: Periodo,
        archivo: ArchivoArchivado,
        nombre_adjunto: str,
    ) -> Correo:
        texto, html = self._render("correo_jefe", self._contexto_periodo(grupo, periodo))
        adjunto = Adjunto(nombre_adjunto, MIME_XLSX, archivo.ruta.read_bytes())
        return Correo(
            para=(grupo.jefe.correo,) if grupo.jefe else (),
            cc=grupo.cc,
            asunto=(
                f"Reporte de asistencia {GUION} {grupo.nombre} {GUION} semana del "
                f"{periodo.texto_asunto()}"
            ),
            texto=texto,
            html=html,
            adjuntos=(adjunto,),
        )

    def correo_sin_registros(self, grupo: Grupo, periodo: Periodo) -> Correo:
        texto, html = self._render("correo_sin_registros", self._contexto_periodo(grupo, periodo))
        return Correo(
            para=(grupo.jefe.correo,) if grupo.jefe else (),
            cc=grupo.cc,
            asunto=(
                f"Reporte de asistencia {GUION} {grupo.nombre} {GUION} semana del "
                f"{periodo.texto_asunto()} (sin registros)"
            ),
            texto=texto,
            html=html,
        )

    def _fila(self, r: ResultadoGrupo) -> dict[str, Any]:
        return {
            "grupo": r.grupo,
            "estado": r.estado.value,
            "color": COLORES[r.estado],
            "filas": "—" if r.filas is None else r.filas,
            "consulta": "—" if r.registros_consulta is None else r.registros_consulta,
            "destinatarios": ", ".join(r.destinatarios) or "—",
            "archivo": r.archivo or "—",
            "intentos": r.intentos,
            "duracion": _duracion(r.duracion_s),
            "error": r.error or "",
            "advertencias": list(r.advertencias),
        }

    def correo_resumen(self, ejecucion: Ejecucion, para: str, adjuntos: Sequence[Path]) -> Correo:
        if ejecucion.error_fatal:
            estado = "ERROR"
        elif any(r.fallido for r in ejecucion.resultados):
            estado = "con fallos"
        elif ejecucion.dias_sin_registros:
            estado = "OK con alertas"
        else:
            estado = "OK"
        contexto = {
            "estado_general": estado,
            "desde": f"{ejecucion.periodo.desde:%d/%m/%Y}",
            "hasta": f"{ejecucion.periodo.hasta:%d/%m/%Y}",
            "modo": ejecucion.modo.value,
            "codigo": ejecucion.codigo_salida,
            "error_fatal": ejecucion.error_fatal or "",
            "dias_sin_registros": _dias(ejecucion.dias_sin_registros),
            "resultados": [self._fila(r) for r in ejecucion.resultados],
            "hay_adjuntos": bool(adjuntos),
            "id": ejecucion.id,
            "inicio": _fecha(ejecucion.inicio),
            "duracion": _duracion(ejecucion.duracion_s),
            "version": self._version,
            "equipo": socket.gethostname(),
        }
        texto, html = self._render("correo_resumen", contexto)
        etiqueta_modo = "" if ejecucion.modo is Modo.PRODUCCION else f" [{ejecucion.modo.value}]"
        return Correo(
            para=(para,),
            asunto=(
                f"[asistencia-bot] {estado} {GUION} semana del {ejecucion.periodo.texto_asunto()}"
                f"{etiqueta_modo}"
            ),
            texto=texto,
            html=html,
            adjuntos=tuple(Adjunto(p.name, _mime(p), p.read_bytes()) for p in adjuntos),
        )

    def correo_alerta_lector(
        self, para: str, ahora: datetime, estado: EstadoLector | None, error: str | None
    ) -> Correo:
        ultimo = estado.ultimo_evento if estado else None
        contexto = {
            "error": error or "",
            "fecha": f"{DIAS_SEMANA[ahora.weekday()]} {ahora:%d/%m/%Y}",
            "hora": f"{ahora:%H:%M}",
            "ultimo": (
                f"{DIAS_SEMANA[ultimo.weekday()]} {ultimo:%d/%m/%Y} a las {ultimo:%H:%M}"
                if ultimo
                else ""
            ),
            "version": self._version,
            "equipo": socket.gethostname(),
        }
        texto, html = self._render("correo_alerta_lector", contexto)
        motivo = "no se pudo revisar el lector" if error else "el lector no envía marcaciones"
        return Correo(
            para=(para,),
            asunto=f"[asistencia-bot] ALERTA {GUION} {motivo} ({ahora:%d/%m %H:%M})",
            texto=texto,
            html=html,
        )

    def resumen_texto(self, ejecucion: Ejecucion) -> str:
        """Resumen en texto plano para la consola (dry-run) sin adjuntos."""
        return self.correo_resumen(ejecucion, "consola@localhost", ()).texto

    def redirigir_a_prueba(self, correo: Correo, administrador: str) -> Correo:
        originales = ", ".join(correo.para) or "(sin jefe configurado)"
        copias = ", ".join(correo.cc) or "—"
        aviso = (
            f"MODO PRUEBA: en producción este correo iría a {originales} (copia: {copias}). "
            "Solo lo recibe el administrador."
        )
        aviso_html = (
            '<p style="padding:8px 10px;background:#fff8e1;border-left:4px solid #f9a825;">'
            f"{escape(aviso)}</p>"
        )
        return Correo(
            para=(administrador,),
            asunto=f"[PRUEBA] {correo.asunto}",
            texto=f"{aviso}\n\n{correo.texto}",
            html=_insertar_tras_body(correo.html, aviso_html),
            adjuntos=correo.adjuntos,
        )


def _insertar_tras_body(html: str, fragmento: str) -> str:
    inicio = html.find("<body")
    if inicio < 0:
        return fragmento + html
    cierre = html.find(">", inicio)
    return html[: cierre + 1] + fragmento + html[cierre + 1 :]
