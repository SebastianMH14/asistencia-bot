"""Precondiciones del entorno, sin iniciar sesión ni exportar."""

import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from asistencia_bot.ports import AlmacenCredenciales

HOSTS_LOCALES = {"127.0.0.1", "localhost", "::1"}


def hikcentral_responde(url: str, host: str, timeout: float = 10) -> str | None:
    """None si responde; si no, el problema. Ignora el certificado solo en el host local."""
    contexto = ssl.create_default_context()
    if host in HOSTS_LOCALES:
        contexto.check_hostname = False
        contexto.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=contexto) as r:
            return None if 200 <= r.status < 400 else f"HikCentral respondió HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return f"HikCentral respondió HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return f"HikCentral no responde en {url}: {type(e).__name__}"


def puerto_abierto(puerto: int, host: str = "127.0.0.1", timeout: float = 3) -> bool:
    try:
        with socket.create_connection((host, puerto), timeout=timeout):
            return True
    except OSError:
        return False


class VerificadorEntornoLocal:
    def __init__(
        self,
        *,
        url_hikcentral: str,
        host_hikcentral: str,
        usuario_hikcentral: str,
        carpeta_descargas: Path,
        puerto_hcwebcontrol: int,
        credenciales: AlmacenCredenciales,
        usuario_smtp: str | None,
    ) -> None:
        self._url, self._host, self._usuario = url_hikcentral, host_hikcentral, usuario_hikcentral
        self._carpeta, self._puerto = carpeta_descargas, puerto_hcwebcontrol
        self._credenciales, self._usuario_smtp = credenciales, usuario_smtp

    def problemas(self) -> list[str]:
        problemas: list[str] = []
        if not self._credenciales.obtener("hikcentral", self._usuario):
            problemas.append(
                f"no hay contraseña de HikCentral para {self._usuario!r} en el Administrador "
                "de credenciales"
            )
        if self._usuario_smtp and not self._credenciales.obtener("smtp", self._usuario_smtp):
            problemas.append(f"no hay contraseña SMTP para {self._usuario_smtp!r}")
        if not self._carpeta.is_dir():
            problemas.append(f"no existe la carpeta de descargas {self._carpeta}")
        if not puerto_abierto(self._puerto):
            problemas.append(
                f"HCWebControl no escucha en 127.0.0.1:{self._puerto}; ¿el usuario de Windows "
                "inició sesión?"
            )
        if error := hikcentral_responde(self._url, self._host):
            problemas.append(error)
        return problemas
