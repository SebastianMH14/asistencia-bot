"""Notificador por SMTP con STARTTLS (smtplib + EmailMessage).

La contraseña se pide a keyring en cada envío y no se guarda en el objeto. Se reintenta
solo ante errores transitorios. Para cambiar a Microsoft Graph basta otro adaptador que
implemente `Notificador`.
"""

import smtplib
import ssl
import time
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from asistencia_bot.domain.errores import ErrorCredenciales, ErrorNotificacion
from asistencia_bot.domain.modelos import Correo
from asistencia_bot.ports import AlmacenCredenciales


def _transitorio(error: BaseException) -> bool:
    """Ojo: SMTPException hereda de OSError; los rechazos permanentes no se reintentan."""
    if isinstance(error, smtplib.SMTPServerDisconnected | smtplib.SMTPConnectError):
        return True
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return False
    if isinstance(error, smtplib.SMTPResponseException):
        return 400 <= error.smtp_code < 500
    if isinstance(error, smtplib.SMTPException):  # p. ej. SMTPRecipientsRefused
        return False
    return isinstance(error, TimeoutError | OSError)


def construir_mensaje(correo: Correo, remitente: str) -> EmailMessage:
    mensaje = EmailMessage()
    mensaje["From"] = remitente
    mensaje["To"] = ", ".join(correo.para)
    if correo.cc:
        mensaje["Cc"] = ", ".join(correo.cc)
    mensaje["Subject"] = correo.asunto
    mensaje["Date"] = formatdate(localtime=True)
    dominio = parseaddr(remitente)[1].partition("@")[2] or None
    mensaje["Message-ID"] = make_msgid(domain=dominio)
    mensaje.set_content(correo.texto)
    mensaje.add_alternative(correo.html, subtype="html")
    for adjunto in correo.adjuntos:
        principal, _, secundario = adjunto.tipo_mime.partition("/")
        mensaje.add_attachment(
            adjunto.contenido,
            maintype=principal,
            subtype=secundario or "octet-stream",
            filename=adjunto.nombre,
        )
    return mensaje


class NotificadorSmtp:
    def __init__(
        self,
        *,
        host: str,
        puerto: int,
        usuario: str,
        remitente: str,
        starttls: bool,
        timeout_s: float,
        reintentos: int,
        credenciales: AlmacenCredenciales,
        espera_s: float = 5.0,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._host, self._puerto, self._usuario = host, puerto, usuario
        self._remitente, self._starttls, self._timeout = remitente, starttls, timeout_s
        self._reintentos, self._espera = reintentos, espera_s
        self._credenciales = credenciales
        self._dormir = dormir

    def _clave(self) -> str:
        clave = self._credenciales.obtener("smtp", self._usuario)
        if not clave:
            raise ErrorCredenciales(
                f"no hay contraseña SMTP para {self._usuario!r}; use "
                "'asistencia-bot credenciales configurar smtp -u <usuario>'"
            )
        return clave

    def _conectar(self) -> smtplib.SMTP:
        servidor = smtplib.SMTP(self._host, self._puerto, timeout=self._timeout)
        try:
            servidor.ehlo()
            if self._starttls:
                servidor.starttls(context=ssl.create_default_context())
                servidor.ehlo()
            servidor.login(self._usuario, self._clave())
        except BaseException:
            servidor.close()
            raise
        return servidor

    def probar(self) -> None:
        """Conecta e inicia sesión sin enviar nada (para `verificar`)."""
        try:
            with self._conectar() as servidor:
                servidor.noop()
        except smtplib.SMTPAuthenticationError:
            raise ErrorCredenciales("el servidor SMTP rechazó usuario o contraseña") from None
        except (smtplib.SMTPException, OSError) as e:
            raise ErrorNotificacion(f"no se pudo conectar al SMTP: {type(e).__name__}") from None

    def enviar(self, correo: Correo) -> None:
        destinatarios = [*correo.para, *correo.cc]
        if not destinatarios:
            raise ErrorNotificacion("el correo no tiene destinatarios")
        mensaje = construir_mensaje(correo, self._remitente)
        reintentador = Retrying(
            stop=stop_after_attempt(self._reintentos),
            wait=wait_exponential(multiplier=self._espera, max=self._espera * 8),
            retry=retry_if_exception(_transitorio),
            reraise=False,
            sleep=self._dormir,
        )
        try:
            for intento in reintentador:
                with intento, self._conectar() as servidor:
                    servidor.send_message(mensaje, to_addrs=destinatarios)
        except smtplib.SMTPAuthenticationError:
            raise ErrorCredenciales("el servidor SMTP rechazó usuario o contraseña") from None
        except RetryError as e:
            causa = e.last_attempt.exception()
            raise ErrorNotificacion(
                f"no se pudo enviar tras {self._reintentos} intentos: {type(causa).__name__}"
            ) from None
        except (smtplib.SMTPException, OSError) as e:
            raise ErrorNotificacion(
                f"el servidor SMTP rechazó el envío: {type(e).__name__}"
            ) from None
