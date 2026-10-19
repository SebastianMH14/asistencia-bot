"""Línea de comandos del bot.

Las contraseñas se piden con ``getpass`` y nunca se imprimen ni se registran.
"""

import getpass
from enum import StrEnum
from typing import Annotated, NoReturn

import typer

from asistencia_bot import __version__, bootstrap

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


def _fallar(mensaje: str) -> NoReturn:
    typer.secho(mensaje, err=True, fg=typer.colors.RED)
    raise typer.Exit(code=1)


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
