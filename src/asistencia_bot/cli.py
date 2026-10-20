"""Línea de comandos del bot.

Códigos de salida de `ejecutar` (los usa el Programador de tareas): 0 todo OK,
1 fallos parciales, 2 error fatal. Las contraseñas se piden con getpass y nunca se imprimen.
"""

import getpass
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from asistencia_bot import __version__, bootstrap
from asistencia_bot.adapters.candado import CandadoArchivo
from asistencia_bot.adapters.entorno import hikcentral_responde, puerto_abierto
from asistencia_bot.config import Configuracion
from asistencia_bot.config import cargar as cargar_config
from asistencia_bot.domain.errores import ErrorBot, ErrorConfiguracion, ErrorEjecucionEnCurso
from asistencia_bot.domain.modelos import Modo
from asistencia_bot.logging_config import configurar_logging
from asistencia_bot.services.ejecutar_reporte_semanal import OpcionesEjecucion

app = typer.Typer(
    name="asistencia-bot",
    help="Bot de reportes semanales de asistencia (HikCentral → correo por grupo).",
    no_args_is_help=True,
    add_completion=False,
)
credenciales_app = typer.Typer(
    help="Contraseñas del bot en el Administrador de credenciales de Windows.",
    no_args_is_help=True,
)
app.add_typer(credenciales_app, name="credenciales")


class Sistema(StrEnum):
    """Sistemas para los que el bot guarda una contraseña."""

    HIKCENTRAL = "hikcentral"
    SMTP = "smtp"


SistemaArg = Annotated[Sistema, typer.Argument(help="Sistema al que pertenece la contraseña.")]
UsuarioOpt = Annotated[str, typer.Option("--usuario", "-u", help="Usuario en ese sistema.")]
ConfigOpt = Annotated[
    Path | None,
    typer.Option(
        "--config", "-c", help="Ruta de settings.toml (por defecto config/settings.toml)."
    ),
]


def _fallar(mensaje: str, codigo: int = 1) -> NoReturn:
    typer.secho(mensaje, err=True, fg=typer.colors.RED)
    raise typer.Exit(code=codigo)


def _cargar(config: Path | None) -> Configuracion:
    try:
        return cargar_config(config)
    except ErrorConfiguracion as e:
        _fallar(str(e), codigo=2)


def _mostrar_version(valor: bool) -> None:
    if valor:
        typer.echo(f"asistencia-bot {__version__}")
        raise typer.Exit()


@app.callback()
def principal(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_mostrar_version,
            is_eager=True,
            help="Muestra la versión y termina.",
        ),
    ] = False,
) -> None:
    """Bot de reportes semanales de asistencia (HikCentral → correo por grupo)."""


# --- ejecutar ---------------------------------------------------------------------------


@app.command()
def ejecutar(
    modo: Annotated[
        Modo | None,
        typer.Option(
            "--modo",
            help="produccion o prueba (def.: ejecucion.modo_por_defecto de la configuración).",
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Exporta y valida, pero no envía ningún correo.")
    ] = False,
    grupo: Annotated[
        list[str] | None, typer.Option("--grupo", "-g", help="Solo este grupo (se puede repetir).")
    ] = None,
    forzar: Annotated[
        bool, typer.Option("--forzar", help="Reenvía aunque ese periodo ya se haya enviado.")
    ] = False,
    visible: Annotated[
        bool, typer.Option("--visible", help="Muestra el navegador (para depurar).")
    ] = False,
    config: ConfigOpt = None,
) -> None:
    """Exporta, valida, archiva y envía el reporte de la semana anterior de cada grupo activo."""
    cfg = _cargar(config)
    elegido = Modo.DRY_RUN if dry_run else (modo or cfg.ajustes.ejecucion.modo_por_defecto)
    if problemas := cfg.problemas_para_modo(elegido):
        _fallar(f"No se puede ejecutar en modo {elegido.value}:\n- " + "\n- ".join(problemas), 2)
    configurar_logging(cfg.ajustes.rutas.logs)
    try:
        with CandadoArchivo(cfg.ajustes.rutas.candado):
            servicio = bootstrap.construir_servicio(cfg, elegido, visible=visible)
            ejecucion = servicio.ejecutar(OpcionesEjecucion(elegido, forzar, tuple(grupo or ())))
    except ErrorEjecucionEnCurso as e:
        _fallar(str(e), 2)
    typer.echo("")
    typer.echo(bootstrap.crear_renderizador().resumen_texto(ejecucion))
    raise typer.Exit(ejecucion.codigo_salida)


# --- verificar --------------------------------------------------------------------------


def _ruta_escribible(base: Path) -> str | None:
    try:
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=base, prefix=".verificar_", delete=True):
            pass
    except OSError as e:
        return f"no se puede escribir en {base}: {type(e).__name__}"
    return None


@app.command()
def verificar(config: ConfigOpt = None) -> None:
    """Revisa configuración, credenciales, SMTP, HikCentral y HCWebControl. No exporta."""
    filas: list[tuple[str, bool, str]] = []
    cfg = _cargar(config)
    a = cfg.ajustes
    modo = a.ejecucion.modo_por_defecto
    filas.append(("configuración", True, f"{cfg.archivo} · {len(cfg.grupos_activos)} grupos"))
    problemas = cfg.problemas_para_modo(modo)
    filas.append((f"modo por defecto ({modo.value})", not problemas, "; ".join(problemas) or "OK"))

    credenciales = bootstrap.crear_almacen_credenciales()
    tiene_hik = bool(credenciales.obtener("hikcentral", a.hikcentral.usuario))
    filas.append(("contraseña de HikCentral", tiene_hik, f"usuario {a.hikcentral.usuario!r}"))

    if a.smtp is None:
        filas.append(("SMTP", not modo.envia_correos, "sin sección [smtp] (solo sirve dry-run)"))
    elif not credenciales.obtener("smtp", a.smtp.usuario):
        filas.append(("SMTP", False, f"no hay contraseña SMTP para {a.smtp.usuario!r}"))
    else:
        notificador = bootstrap.crear_notificador(a, credenciales)
        try:
            if notificador is not None:
                notificador.probar()
            filas.append(("SMTP", True, f"{a.smtp.host}:{a.smtp.puerto} conexión y login OK"))
        except ErrorBot as e:
            filas.append(("SMTP", False, str(e)))

    carpeta = a.hikcentral.carpeta_descargas
    filas.append(("carpeta Downloadcenter", carpeta.is_dir(), str(carpeta)))
    hcweb = puerto_abierto(a.hikcentral.puerto_hcwebcontrol)
    filas.append(
        (
            "HCWebControl",
            hcweb,
            f"127.0.0.1:{a.hikcentral.puerto_hcwebcontrol}"
            + ("" if hcweb else " no responde: ¿el usuario de Windows inició sesión?"),
        )
    )
    error_hik = hikcentral_responde(a.hikcentral.url, a.hikcentral.host)
    filas.append(("HikCentral", error_hik is None, error_hik or a.hikcentral.url))
    error_ruta = _ruta_escribible(a.rutas.base)
    filas.append(("carpeta del bot", error_ruta is None, error_ruta or str(a.rutas.base)))

    ancho = max(len(nombre) for nombre, _, _ in filas)
    for nombre, ok, detalle in filas:
        marca = (
            typer.style("OK   ", fg=typer.colors.GREEN)
            if ok
            else typer.style("FALLA", fg=typer.colors.RED)
        )
        typer.echo(f"{marca} {nombre:<{ancho}}  {detalle}")
    raise typer.Exit(0 if all(ok for _, ok, _ in filas) else 2)


# --- estado -----------------------------------------------------------------------------


@app.command()
def estado(
    n: Annotated[int, typer.Option("-n", help="Cuántas ejecuciones mostrar.")] = 10,
    config: ConfigOpt = None,
) -> None:
    """Muestra las últimas ejecuciones y el resultado de cada grupo."""
    cfg = _cargar(config)
    ejecuciones = bootstrap.crear_estado(cfg.ajustes).ultimas_ejecuciones(n)
    if not ejecuciones:
        typer.echo("No hay ejecuciones registradas.")
        return
    for e in ejecuciones:
        typer.echo(
            f"{e.inicio:%Y-%m-%d %H:%M}  {e.modo.value:<10} semana {e.periodo.texto_hik()}  "
            f"código {e.codigo_salida}  [{e.id[:8]}]"
        )
        if e.error_fatal:
            typer.echo(f"    error fatal: {e.error_fatal}")
        if e.error_resumen:
            typer.echo(f"    resumen: {e.error_resumen}")
        for r in e.resultados:
            filas = f" ({r.filas} filas)" if r.filas is not None else ""
            error = f" — {r.error}" if r.error else ""
            typer.echo(f"    - {r.grupo}: {r.estado.value}{filas}{error}")


# --- credenciales -----------------------------------------------------------------------


@credenciales_app.command("configurar")
def configurar(sistema: SistemaArg, usuario: UsuarioOpt) -> None:
    """Pide la contraseña (sin mostrarla) y la guarda en el Administrador de credenciales."""
    secreto = getpass.getpass(f"Contraseña de {sistema.value} para el usuario '{usuario}': ")
    if not secreto:
        _fallar("No se escribió ninguna contraseña; no se guardó nada.")
    if getpass.getpass("Repite la contraseña: ") != secreto:
        _fallar("Las contraseñas no coinciden; no se guardó nada.")
    bootstrap.crear_almacen_credenciales().guardar(sistema.value, usuario, secreto)
    typer.echo(
        f"Contraseña de {sistema.value} para '{usuario}' guardada en el "
        "Administrador de credenciales de Windows."
    )


@credenciales_app.command("comprobar")
def comprobar(sistema: SistemaArg, usuario: UsuarioOpt) -> None:
    """Indica si hay una contraseña guardada, sin mostrarla."""
    if bootstrap.crear_almacen_credenciales().obtener(sistema.value, usuario) is None:
        _fallar(
            f"No hay contraseña de {sistema.value} para '{usuario}'. Configúrala con: "
            f"asistencia-bot credenciales configurar {sistema.value} --usuario {usuario}"
        )
    typer.echo(f"Hay una contraseña de {sistema.value} guardada para '{usuario}'.")


@credenciales_app.command("borrar")
def borrar(sistema: SistemaArg, usuario: UsuarioOpt) -> None:
    """Elimina la contraseña guardada."""
    if not bootstrap.crear_almacen_credenciales().borrar(sistema.value, usuario):
        _fallar(f"No había contraseña de {sistema.value} para '{usuario}'.")
    typer.echo(f"Contraseña de {sistema.value} para '{usuario}' eliminada.")
