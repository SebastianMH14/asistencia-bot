"""Navegador, contexto, guarda de hosts, trace por tramos y evidencias.

El trace de Playwright registra el texto de los `fill`, por eso:
- empieza solo DESPUÉS del login,
- cubre la navegación y la selección de cada grupo,
- se pausa ANTES de abrir el panel de exportación (contraseña de confirmación),
- y cada grupo arranca con la página recargada, sin contraseñas en el DOM.
Capturas y traces son sensibles (datos personales): solo local y solo para el administrador.
"""

import contextlib
import logging
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from asistencia_bot.domain.errores import ErrorEntorno

log = logging.getLogger(__name__)


class SesionNavegador:
    def __init__(
        self,
        *,
        url: str,
        navegador: str,
        headless: bool,
        timeout_ui_s: float,
        carpeta_capturas: Path,
        carpeta_traces: Path,
        trace_en_error: bool,
    ) -> None:
        self.url = url
        self._host = urlparse(url).hostname or ""
        self._canal = navegador
        self._headless = headless
        self.timeout_ms = timeout_ui_s * 1000
        self._capturas = carpeta_capturas
        self._traces = carpeta_traces
        self._trace_en_error = trace_en_error
        self._pw: Playwright | None = None
        self._navegador: Browser | None = None
        self._contexto: BrowserContext | None = None
        self._page: Page | None = None
        self._trace_iniciado = False
        self._tramo_activo = False
        self._tramo_pendiente: Path | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise ErrorEntorno("el navegador no está abierto")
        return self._page

    def _solo_host_local(self, route: Route) -> None:
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")) or urlparse(url).hostname == self._host:
            route.continue_()
        else:
            log.warning(
                "petición bloqueada a un host externo", extra={"host": urlparse(url).hostname}
            )
            route.abort()

    def abrir(self) -> Page:
        try:
            self._pw = sync_playwright().start()
            self._navegador = self._pw.chromium.launch(channel=self._canal, headless=self._headless)
            # ignore_https_errors es seguro aquí: la ruta de abajo aborta todo host externo.
            self._contexto = self._navegador.new_context(
                ignore_https_errors=True,
                viewport={"width": 1600, "height": 900},
                locale="es-ES",
            )
            self._contexto.route("**/*", self._solo_host_local)
            self._contexto.set_default_timeout(self.timeout_ms)
            self._page = self._contexto.new_page()
            self._page.goto(self.url, wait_until="domcontentloaded")
        except PlaywrightError as e:
            self.cerrar()
            raise ErrorEntorno(
                f"no se pudo abrir {self._canal} o cargar HikCentral: {resumir_error(e)}"
            ) from None
        return self._page

    def recargar(self) -> None:
        """Estado limpio para cada grupo (y sin contraseñas en el DOM).

        Recarga real de la ruta actual. No usar goto(url): con sesión iniciada la página está en
        `#/portal?...` y un goto a `#/` solo cambia el hash, sin recargar; la aplicación queda
        en una ruta intermedia sin el menú superior (así falló el primer dry-run).
        """
        self.page.reload(wait_until="domcontentloaded")

    # --- trace por tramos -----------------------------------------------------------------

    def iniciar_tramo(self) -> None:
        if not self._trace_en_error or self._contexto is None or self._tramo_activo:
            return
        self._descartar_pendiente()
        if not self._trace_iniciado:
            self._contexto.tracing.start(screenshots=True, snapshots=True)
            self._trace_iniciado = True
        else:
            self._contexto.tracing.start_chunk()
        self._tramo_activo = True

    def pausar_tramo(self) -> None:
        """Antes de cualquier contraseña: guarda el tramo como pendiente por si el grupo falla."""
        if not self._tramo_activo or self._contexto is None:
            return
        self._traces.mkdir(parents=True, exist_ok=True)
        self._tramo_pendiente = self._traces / "_tramo_pendiente.zip"
        self._contexto.tracing.stop_chunk(path=self._tramo_pendiente)
        self._tramo_activo = False

    def _descartar_pendiente(self) -> None:
        if self._tramo_pendiente is not None:
            self._tramo_pendiente.unlink(missing_ok=True)
            self._tramo_pendiente = None

    def guardar_evidencia(self, etiqueta: str) -> tuple[Path, ...]:
        evidencias: list[Path] = []
        if self._page is not None:
            with contextlib.suppress(PlaywrightError):
                self._capturas.mkdir(parents=True, exist_ok=True)
                captura = self._capturas / f"{etiqueta}.png"
                self._page.screenshot(path=captura)
                evidencias.append(captura)
        destino = self._traces / f"{etiqueta}.zip"
        with contextlib.suppress(PlaywrightError, OSError):
            if self._tramo_activo and self._contexto is not None:
                self._traces.mkdir(parents=True, exist_ok=True)
                self._contexto.tracing.stop_chunk(path=destino)
                self._tramo_activo = False
                evidencias.append(destino)
            elif self._tramo_pendiente is not None and self._tramo_pendiente.exists():
                self._tramo_pendiente.replace(destino)
                self._tramo_pendiente = None
                evidencias.append(destino)
        return tuple(evidencias)

    def grupo_terminado(self) -> None:
        """Éxito: no se guarda nada del trace."""
        if self._tramo_activo and self._contexto is not None:
            with contextlib.suppress(PlaywrightError):
                self._contexto.tracing.stop_chunk()
            self._tramo_activo = False
        self._descartar_pendiente()

    def cerrar(self) -> None:
        with contextlib.suppress(Exception):
            if self._trace_iniciado and self._contexto is not None:
                self._contexto.tracing.stop()
        self._descartar_pendiente()
        for cierre in (
            self._contexto.close if self._contexto else None,
            self._navegador.close if self._navegador else None,
            self._pw.stop if self._pw else None,
        ):
            if cierre is not None:
                with contextlib.suppress(Exception):
                    cierre()
        self._pw = self._navegador = self._contexto = self._page = None
        self._trace_iniciado = self._tramo_activo = False


def resumir_error(error: BaseException) -> str:
    """Primera línea del error y el selector que se esperaba.

    Del call log solo se toma la línea "waiting for <selector>" (es el selector del bot);
    el resto puede traer HTML de la página y se descarta.
    """
    cabeza, _, call_log = str(error).partition("Call log:")
    lineas = cabeza.strip().splitlines()
    resumen = f"{type(error).__name__}: {lineas[0][:200] if lineas else ''}".rstrip(": ")
    esperando = next(
        (
            linea.strip().lstrip("- ").strip()
            for linea in call_log.splitlines()
            if linea.strip().lstrip("- ").startswith("waiting for")
        ),
        None,
    )
    return f"{resumen} ({esperando[:160]})" if esperando else resumen
