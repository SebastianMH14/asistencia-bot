"""Plantillas y SMTP. El servidor SMTP es falso: nunca se conecta a uno real."""

import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, ClassVar

import pytest

from asistencia_bot.adapters.correo_smtp import NotificadorSmtp, construir_mensaje
from asistencia_bot.adapters.plantillas import GUION, MIME_XLSX, RenderizadorJinja
from asistencia_bot.domain.errores import ErrorCredenciales, ErrorNotificacion
from asistencia_bot.domain.modelos import (
    ArchivoArchivado,
    Correo,
    Ejecucion,
    EstadoGrupo,
    Grupo,
    Jefe,
    Modo,
    Periodo,
    ResultadoGrupo,
)

SEMANA = Periodo(date(2026, 10, 12), date(2026, 10, 18))
GRUPO = Grupo("Fisioterapeutas", "Fisioterapeutas", Jefe("Jefa", "jefa@x.co"), ("cc@x.co",))
render = RenderizadorJinja("0.1.0")


def _archivo(tmp_path: Path) -> ArchivoArchivado:
    ruta = tmp_path / "Asistencia_Fisioterapeutas_2026-10-12_al_2026-10-18.xlsx"
    ruta.write_bytes(b"xlsx-bytes")
    return ArchivoArchivado(ruta, "abc", 10)


# --- plantillas ---------------------------------------------------------------------------


def test_correo_jefe(tmp_path: Path) -> None:
    archivo = _archivo(tmp_path)

    correo = render.correo_jefe(GRUPO, SEMANA, archivo, archivo.ruta.name)

    assert correo.asunto == (
        f"Reporte de asistencia {GUION} Fisioterapeutas {GUION} semana del 12/10 al 18/10/2026"
    )
    assert correo.para == ("jefa@x.co",) and correo.cc == ("cc@x.co",)
    assert "no marcó salida" in correo.texto and "una sola marcación" in correo.texto
    assert "<strong>Fisioterapeutas</strong>" in correo.html
    [adjunto] = correo.adjuntos
    assert adjunto.contenido == b"xlsx-bytes" and adjunto.tipo_mime == MIME_XLSX


def test_html_escapa_nombres(tmp_path: Path) -> None:
    grupo = Grupo("<script>", "x", Jefe("J", "j@x.co"))

    correo = render.correo_jefe(grupo, SEMANA, _archivo(tmp_path), "a.xlsx")

    assert "<script>" not in correo.html and "&lt;script&gt;" in correo.html


def test_correo_sin_registros() -> None:
    correo = render.correo_sin_registros(GRUPO, SEMANA)

    assert correo.asunto.endswith("(sin registros)")
    assert correo.adjuntos == ()


def test_redirigir_a_prueba(tmp_path: Path) -> None:
    original = render.correo_jefe(GRUPO, SEMANA, _archivo(tmp_path), "a.xlsx")

    prueba = render.redirigir_a_prueba(original, "admin@x.co")

    assert prueba.para == ("admin@x.co",) and prueba.cc == ()
    assert prueba.asunto.startswith("[PRUEBA] ")
    assert "jefa@x.co" in prueba.texto and "cc@x.co" in prueba.texto
    assert prueba.html.index("MODO PRUEBA") > prueba.html.index("<body")
    assert prueba.adjuntos == original.adjuntos


def test_resumen(tmp_path: Path) -> None:
    e = Ejecucion("abcdef12", datetime(2026, 10, 19, 7), Modo.PRUEBA, SEMANA, "0.1.0")
    e.resultados = [
        ResultadoGrupo(
            "Fisioterapeutas",
            EstadoGrupo.ENVIADO,
            filas=65,
            registros_consulta=65,
            destinatarios=("admin@x.co",),
        ),
        ResultadoGrupo(
            "Médicos", EstadoGrupo.FALLIDO, error="no apareció el archivo", advertencias=("ojo",)
        ),
    ]
    e.fin = datetime(2026, 10, 19, 7, 3)
    captura = tmp_path / "abcdef12_Medicos.png"
    captura.write_bytes(b"png")

    correo = render.correo_resumen(e, "admin@x.co", [captura])

    assert correo.asunto.startswith("[asistencia-bot] con fallos")
    assert "[prueba]" in correo.asunto
    assert "no apareció el archivo" in correo.texto and "ojo" in correo.texto
    assert "3 min 00 s" in correo.texto
    assert correo.adjuntos[0].tipo_mime == "image/png"
    assert "no los reenvíe" in correo.html


def test_resumen_error_fatal_y_texto_consola() -> None:
    e = Ejecucion(
        "x",
        datetime(2026, 10, 19, 7),
        Modo.DRY_RUN,
        SEMANA,
        "0.1.0",
        error_fatal="HikCentral no responde",
    )

    texto = render.resumen_texto(e)

    assert "ERROR FATAL: HikCentral no responde" in texto
    assert "No se procesó ningún grupo" in texto


# --- SMTP ---------------------------------------------------------------------------------


class SmtpFalso:
    enviados: ClassVar[list[tuple[EmailMessage, list[str]]]] = []
    fallos: ClassVar[list[BaseException]] = []
    logins: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, host: str, puerto: int, timeout: float) -> None:
        self.host = host

    def __enter__(self) -> "SmtpFalso":
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def ehlo(self) -> None:
        pass

    def starttls(self, context: Any = None) -> None:
        pass

    def login(self, usuario: str, clave: str) -> None:
        SmtpFalso.logins.append((usuario, clave))

    def noop(self) -> None:
        pass

    def close(self) -> None:
        pass

    def send_message(self, mensaje: EmailMessage, to_addrs: list[str]) -> None:
        if SmtpFalso.fallos:
            raise SmtpFalso.fallos.pop(0)
        SmtpFalso.enviados.append((mensaje, to_addrs))


class Credenciales:
    def __init__(self, clave: str | None = "secreta") -> None:
        self.clave = clave

    def obtener(self, sistema: str, usuario: str) -> str | None:
        return self.clave

    def guardar(self, sistema: str, usuario: str, secreto: str) -> None: ...

    def borrar(self, sistema: str, usuario: str) -> bool:
        return False


@pytest.fixture(autouse=True)
def smtp_falso(monkeypatch: pytest.MonkeyPatch) -> None:
    SmtpFalso.enviados, SmtpFalso.fallos, SmtpFalso.logins = [], [], []
    monkeypatch.setattr(smtplib, "SMTP", SmtpFalso)


def _notificador(clave: str | None = "secreta") -> NotificadorSmtp:
    return NotificadorSmtp(
        host="smtp.x.co",
        puerto=587,
        usuario="bot@x.co",
        remitente="Bot <bot@x.co>",
        starttls=True,
        timeout_s=5,
        reintentos=3,
        credenciales=Credenciales(clave),
        espera_s=0,
        dormir=lambda _: None,
    )


def _correo() -> Correo:
    return Correo(("jefa@x.co",), "Asunto", "texto", "<p>html</p>", cc=("cc@x.co",))


def test_envia_con_copia_y_login() -> None:
    _notificador().enviar(_correo())

    [(mensaje, destinos)] = SmtpFalso.enviados
    assert destinos == ["jefa@x.co", "cc@x.co"]
    assert mensaje["Cc"] == "cc@x.co" and mensaje["From"] == "Bot <bot@x.co>"
    assert SmtpFalso.logins == [("bot@x.co", "secreta")]


def test_reintenta_errores_transitorios() -> None:
    SmtpFalso.fallos = [smtplib.SMTPServerDisconnected("x"), TimeoutError()]

    _notificador().enviar(_correo())

    assert len(SmtpFalso.enviados) == 1


def test_agota_reintentos() -> None:
    SmtpFalso.fallos = [TimeoutError()] * 3

    with pytest.raises(ErrorNotificacion, match="tras 3 intentos"):
        _notificador().enviar(_correo())


def test_no_reintenta_rechazo_permanente() -> None:
    SmtpFalso.fallos = [smtplib.SMTPRecipientsRefused({"jefa@x.co": (550, b"no")})]

    with pytest.raises(ErrorNotificacion, match="rechazó el envío"):
        _notificador().enviar(_correo())
    assert SmtpFalso.fallos == []


def test_autenticacion_rechazada_es_error_de_credenciales() -> None:
    SmtpFalso.fallos = [smtplib.SMTPAuthenticationError(535, b"bad")]

    with pytest.raises(ErrorCredenciales):
        _notificador().enviar(_correo())


def test_sin_clave_en_keyring() -> None:
    with pytest.raises(ErrorCredenciales, match="credenciales configurar smtp"):
        _notificador(clave=None).enviar(_correo())


def test_sin_destinatarios() -> None:
    with pytest.raises(ErrorNotificacion, match="no tiene destinatarios"):
        _notificador().enviar(Correo((), "a", "b", "c"))


def test_probar() -> None:
    _notificador().probar()

    assert SmtpFalso.logins and not SmtpFalso.enviados


def test_mensaje_con_adjunto(tmp_path: Path) -> None:
    correo = render.correo_jefe(GRUPO, SEMANA, _archivo(tmp_path), "reporte.xlsx")

    mensaje = construir_mensaje(correo, "Bot <bot@x.co>")

    [adjunto] = list(mensaje.iter_attachments())
    assert adjunto.get_filename() == "reporte.xlsx"
    assert adjunto.get_content() == b"xlsx-bytes"
    assert mensaje["Message-ID"].endswith("@x.co>")
