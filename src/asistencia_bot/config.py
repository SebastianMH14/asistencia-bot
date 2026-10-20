"""Configuración: ajustes en TOML (sobrescribibles por variables de entorno) y grupos en YAML.

Los secretos nunca van aquí: la contraseña de HikCentral y la del SMTP están en keyring.
Variables de entorno: prefijo ``ASISTENCIA_BOT_`` y ``__`` para anidar, p. ej.
``ASISTENCIA_BOT_HIKCENTRAL__HEADLESS=false``. ``ASISTENCIA_BOT_CONFIG`` apunta al TOML.
"""

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from asistencia_bot.domain.errores import ErrorConfiguracion
from asistencia_bot.domain.modelos import Grupo, Jefe, Modo, PoliticaSinRegistros

PATRON_CORREO = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


def _validar_correo(valor: str) -> str:
    valor = valor.strip()
    if not PATRON_CORREO.match(valor):
        raise ValueError("no es un correo válido")
    return valor


CorreoStr = Annotated[str, AfterValidator(_validar_correo)]


class _Modelo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConfigHikCentral(_Modelo):
    url: str = "https://127.0.0.1/#/"
    usuario: str = Field(default="admin", min_length=1)
    navegador: Literal["msedge", "chrome"] = "msedge"
    headless: bool = True
    timeout_ui_s: float = Field(default=30, gt=0)
    timeout_captura_s: float = Field(default=120, gt=0)
    # Por defecto, la carpeta que usa HCWebControl en el perfil del usuario de Windows.
    carpeta_descargas: Path = Field(
        default_factory=lambda: Path.home() / "HCWebControlService" / "Downloadcenter"
    )
    puerto_hcwebcontrol: int = Field(default=15000, gt=0, lt=65536)
    trace_en_error: bool = True

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or ""


class ConfigEjecucion(_Modelo):
    zona_horaria: str = "America/Bogota"
    modo_por_defecto: Modo = Modo.PRUEBA
    produccion_habilitada: bool = False
    reintentos: int = Field(default=3, ge=1, le=10)
    espera_inicial_s: float = Field(default=30, ge=0)
    espera_maxima_s: float = Field(default=120, ge=0)
    sin_registros: PoliticaSinRegistros = PoliticaSinRegistros.OMITIR_Y_REPORTAR

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        try:
            ZoneInfo(self.zona_horaria)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"zona horaria desconocida: {self.zona_horaria}") from e
        if self.espera_maxima_s < self.espera_inicial_s:
            raise ValueError("espera_maxima_s debe ser >= espera_inicial_s")
        if self.modo_por_defecto is Modo.PRODUCCION and not self.produccion_habilitada:
            raise ValueError(
                "modo_por_defecto = 'produccion' requiere produccion_habilitada = true"
            )
        return self


class ConfigRutas(_Modelo):
    base: Path

    @property
    def salida(self) -> Path:
        return self.base / "salida"

    @property
    def logs(self) -> Path:
        return self.base / "logs"

    @property
    def capturas(self) -> Path:
        return self.base / "capturas"

    @property
    def traces(self) -> Path:
        return self.base / "traces"

    @property
    def estado_db(self) -> Path:
        return self.base / "estado.db"

    @property
    def candado(self) -> Path:
        return self.base / "ejecucion.lock"


class ConfigRetencion(_Modelo):
    excel_dias: int = Field(default=180, ge=1)
    logs_dias: int = Field(default=90, ge=1)
    evidencias_dias: int = Field(default=90, ge=1)


class ConfigSmtp(_Modelo):
    host: str = Field(min_length=1)
    puerto: int = Field(default=587, gt=0, lt=65536)
    usuario: str = Field(min_length=1)
    remitente: str = Field(min_length=3)
    starttls: bool = True
    timeout_s: float = Field(default=30, gt=0)
    reintentos: int = Field(default=3, ge=1, le=10)


class ConfigAdministrador(_Modelo):
    correo: CorreoStr


class Ajustes(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASISTENCIA_BOT_", env_nested_delimiter="__", extra="forbid", frozen=True
    )

    hikcentral: ConfigHikCentral = ConfigHikCentral()
    ejecucion: ConfigEjecucion = ConfigEjecucion()
    rutas: ConfigRutas
    retencion: ConfigRetencion = ConfigRetencion()
    smtp: ConfigSmtp | None = None
    administrador: ConfigAdministrador | None = None
    archivo_grupos: Path = Path("grupos.yaml")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # El TOML llega como init; el entorno lo sobrescribe. Sin .env: los secretos van en keyring.
        return (env_settings, init_settings)


class JefeConfig(_Modelo):
    nombre: str = Field(min_length=1)
    correo: CorreoStr


class GrupoConfig(_Modelo):
    nombre: str = Field(min_length=1)
    departamento_hik: str = Field(min_length=1)
    activo: bool = True
    jefe: JefeConfig | None = None
    cc: list[CorreoStr] = Field(default_factory=list)

    def a_dominio(self) -> Grupo:
        jefe = Jefe(self.jefe.nombre, self.jefe.correo) if self.jefe else None
        return Grupo(self.nombre, self.departamento_hik, jefe, tuple(self.cc), self.activo)


class GruposConfig(_Modelo):
    grupos: list[GrupoConfig]

    @model_validator(mode="after")
    def _coherente(self) -> Self:
        nombres = [g.nombre.casefold() for g in self.grupos]
        repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
        if repetidos:
            raise ValueError(f"nombres de grupo repetidos: {', '.join(repetidos)}")
        if not any(g.activo for g in self.grupos):
            raise ValueError("no hay ningún grupo activo")
        return self


@dataclass(frozen=True, slots=True)
class Configuracion:
    ajustes: Ajustes
    grupos: tuple[Grupo, ...]
    archivo: Path

    @property
    def grupos_activos(self) -> tuple[Grupo, ...]:
        return tuple(g for g in self.grupos if g.activo)

    def problemas_para_modo(self, modo: Modo) -> list[str]:
        """Requisitos que dependen del modo (producción exige más que dry-run)."""
        problemas: list[str] = []
        if modo is Modo.PRODUCCION and not self.ajustes.ejecucion.produccion_habilitada:
            problemas.append(
                "el modo producción no está habilitado (ejecucion.produccion_habilitada = false)"
            )
        if modo.envia_correos:
            if self.ajustes.smtp is None:
                problemas.append("falta la sección [smtp]")
            if self.ajustes.administrador is None:
                problemas.append("falta la sección [administrador]")
        if modo is Modo.PRODUCCION:
            sin_jefe = [g.nombre for g in self.grupos_activos if g.jefe is None]
            if sin_jefe:
                problemas.append(f"grupos activos sin jefe: {', '.join(sin_jefe)}")
        return problemas


def _resumir(error: ValidationError, archivo: Path) -> str:
    partes = [
        f"{'.'.join(str(p) for p in e['loc']) or '(raíz)'}: {e['msg']}"
        for e in error.errors(include_input=False, include_url=False)
    ]
    return f"configuración inválida en {archivo}: " + "; ".join(partes)


def ruta_por_defecto() -> Path:
    """``$ASISTENCIA_BOT_CONFIG`` o ``config/settings.toml`` (directorio actual o proyecto)."""
    if env := os.environ.get("ASISTENCIA_BOT_CONFIG"):
        return Path(env)
    candidatas = [
        Path.cwd() / "config" / "settings.toml",
        Path(__file__).resolve().parents[2] / "config" / "settings.toml",
    ]
    return next((c for c in candidatas if c.exists()), candidatas[0])


def cargar_grupos(ruta: Path) -> tuple[Grupo, ...]:
    if not ruta.exists():
        raise ErrorConfiguracion(f"no existe {ruta}; copie config/grupos.example.yaml y complételo")
    try:
        datos: Any = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        return tuple(g.a_dominio() for g in GruposConfig.model_validate(datos).grupos)
    except yaml.YAMLError as e:
        raise ErrorConfiguracion(f"YAML inválido en {ruta}: {e}") from None
    except ValidationError as e:
        raise ErrorConfiguracion(_resumir(e, ruta)) from None


def cargar(ruta: Path | None = None) -> Configuracion:
    ruta = (ruta or ruta_por_defecto()).resolve()
    if not ruta.exists():
        raise ErrorConfiguracion(
            f"no existe {ruta}; copie config/settings.example.toml a config/settings.toml"
        )
    try:
        datos: dict[str, Any] = tomllib.loads(ruta.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ErrorConfiguracion(f"TOML inválido en {ruta}: {e}") from None
    # Por defecto, la base es la raíz del proyecto (config/ está dentro de ella).
    datos.setdefault("rutas", {}).setdefault("base", str(ruta.parent.parent))
    try:
        ajustes = Ajustes(**datos)
    except ValidationError as e:
        raise ErrorConfiguracion(_resumir(e, ruta)) from None
    archivo_grupos = ajustes.archivo_grupos
    if not archivo_grupos.is_absolute():
        archivo_grupos = ruta.parent / archivo_grupos
    return Configuracion(ajustes, cargar_grupos(archivo_grupos), ruta)
