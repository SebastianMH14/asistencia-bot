"""Servicio orquestador con fakes de todos los puertos (sin HikCentral, SMTP ni disco real)."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from asistencia_bot.domain.errores import (
    ErrorCaptura,
    ErrorCredenciales,
    ErrorExtraccion,
    ErrorLogin,
    ErrorNotificacion,
    ErrorPeriodoNoCoincide,
)
from asistencia_bot.domain.modelos import (
    ArchivoArchivado,
    ConsultaInterfaz,
    Correo,
    Ejecucion,
    EstadoGrupo,
    Grupo,
    Jefe,
    MetadatosReporte,
    Modo,
    Periodo,
    PoliticaSinRegistros,
    ReporteExportado,
    ResultadoGrupo,
)
from asistencia_bot.domain.validacion import ENCABEZADOS_REQUERIDOS
from asistencia_bot.services.ejecutar_reporte_semanal import (
    EjecutarReporteSemanal,
    OpcionesEjecucion,
    PoliticaReintentos,
)

SEMANA = Periodo(date(2026, 10, 12), date(2026, 10, 18))
LUNES = datetime(2026, 10, 19, 7, 0, tzinfo=ZoneInfo("America/Bogota"))
ADMIN = "admin@x.co"
FISIO = Grupo("Fisioterapeutas", "Fisioterapeutas", Jefe("A", "fisio@x.co"), ("cc@x.co",))
MEDICOS = Grupo("Médicos", "Medicos", Jefe("B", "medicos@x.co"))
TI = Grupo("TI", "TI", activo=False)


def _claves(n: int) -> frozenset[tuple[str, date]]:
    return frozenset((f"E{i}", date(2026, 10, 12 + i % 5)) for i in range(n))


class Reloj:
    def ahora(self) -> datetime:
        return LUNES


@dataclass
class Entorno:
    lista: list[str] = field(default_factory=list)

    def problemas(self) -> list[str]:
        return self.lista


@dataclass
class Extractor:
    tmp: Path
    guion: dict[str, list[int | Exception]]  # por grupo: filas a exportar o error por intento
    abierto: bool = False
    cerrado: bool = False
    exportados: list[str] = field(default_factory=list)
    error_abrir: Exception | None = None

    def abrir(self) -> None:
        if self.error_abrir:
            raise self.error_abrir
        self.abierto = True

    def exportar(self, grupo: Grupo, periodo: Periodo) -> ReporteExportado:
        self.exportados.append(grupo.nombre)
        paso = self.guion[grupo.nombre].pop(0)
        if isinstance(paso, Exception):
            raise paso
        ruta = self.tmp / f"{grupo.slug}_{len(self.exportados)}.xlsx"
        ruta.write_text(str(paso))
        consulta = ConsultaInterfaz(1, paso, periodo, _claves(paso))
        return ReporteExportado(grupo.nombre, ruta, 1, consulta)

    def guardar_evidencia(self, etiqueta: str) -> tuple[Path, ...]:
        captura = self.tmp / f"{etiqueta}.png"
        captura.write_bytes(b"png")
        return (captura,)

    def cerrar(self) -> None:
        self.cerrado = True


@dataclass
class Inspector:
    grupo_por_ruta: dict[str, str] = field(default_factory=dict)
    periodo_texto: str = SEMANA.texto_hik()

    def leer_metadatos(self, ruta: Path) -> MetadatosReporte:
        filas = int(ruta.read_text())
        depto = "General>Medicos" if ruta.name.startswith("Medicos") else "General>Fisioterapeutas"
        return MetadatosReporte(
            hoja="Sheet1",
            titulo="Registros de entradas y salidas",
            periodo_texto=self.periodo_texto,
            encabezados=ENCABEZADOS_REQUERIDOS,
            departamentos=frozenset({depto}) if filas else frozenset(),
            filas=filas,
            claves=_claves(filas),
        )


@dataclass
class Archivador:
    tmp: Path
    archivados: list[str] = field(default_factory=list)
    limpiezas: int = 0

    def archivar(self, origen: Path, periodo: Periodo, grupo: Grupo) -> ArchivoArchivado:
        destino = self.tmp / f"Asistencia_{grupo.slug}.xlsx"
        destino.write_bytes(origen.read_bytes())
        self.archivados.append(grupo.nombre)
        return ArchivoArchivado(destino, f"sha-{grupo.slug}", 1)

    def limpiar(self, ahora: datetime) -> int:
        self.limpiezas += 1
        return 0


@dataclass
class Notificador:
    enviados: list[Correo] = field(default_factory=list)
    fallar: dict[str, Exception] = field(default_factory=dict)  # por fragmento de asunto

    def enviar(self, correo: Correo) -> None:
        for fragmento, error in self.fallar.items():
            if fragmento in correo.asunto:
                raise error
        self.enviados.append(correo)


class Renderizador:
    def __init__(self) -> None:
        self.adjuntos: list[str] = []

    def correo_jefe(
        self, grupo: Grupo, periodo: Periodo, archivo: ArchivoArchivado, nombre_adjunto: str
    ) -> Correo:
        self.adjuntos.append(nombre_adjunto)
        para = (grupo.jefe.correo,) if grupo.jefe else ()
        return Correo(para, f"Reporte {grupo.nombre}", "t", "h", cc=grupo.cc)

    def correo_sin_registros(self, grupo: Grupo, periodo: Periodo) -> Correo:
        para = (grupo.jefe.correo,) if grupo.jefe else ()
        return Correo(para, f"Sin registros {grupo.nombre}", "t", "h")

    def correo_resumen(self, ejecucion: Ejecucion, para: str, adjuntos: Sequence[Path]) -> Correo:
        return Correo((para,), f"Resumen {len(adjuntos)} adjuntos", "t", "h")

    def redirigir_a_prueba(self, correo: Correo, administrador: str) -> Correo:
        return Correo((administrador,), f"[PRUEBA] {correo.asunto}", "t", "h")


@dataclass
class Estado:
    enviados_produccion: set[tuple[Periodo, str]] = field(default_factory=set)
    registrados: list[ResultadoGrupo] = field(default_factory=list)
    finalizada: Ejecucion | None = None

    def iniciar_ejecucion(self, ejecucion: Ejecucion) -> None: ...

    def registrar_resultado(self, ejecucion: Ejecucion, resultado: ResultadoGrupo) -> None:
        self.registrados.append(resultado)

    def finalizar_ejecucion(self, ejecucion: Ejecucion) -> None:
        self.finalizada = ejecucion

    def ya_enviado(self, periodo: Periodo, grupo: str) -> bool:
        return (periodo, grupo) in self.enviados_produccion

    def ultimas_ejecuciones(self, n: int) -> list[Ejecucion]:
        return []


@dataclass
class Escenario:
    tmp: Path
    guion: dict[str, list[int | Exception]] = field(default_factory=dict)
    grupos: tuple[Grupo, ...] = (FISIO, MEDICOS, TI)
    sin_registros: PoliticaSinRegistros = PoliticaSinRegistros.OMITIR_Y_REPORTAR
    con_notificador: bool = True
    esperas: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.entorno = Entorno()
        self.extractor = Extractor(self.tmp, self.guion)
        self.inspector = Inspector()
        self.archivador = Archivador(self.tmp)
        self.notificador = Notificador()
        self.estado = Estado()
        self.renderizador = Renderizador()

    def ejecutar(self, modo: Modo, **opciones: object) -> Ejecucion:
        servicio = EjecutarReporteSemanal(
            reloj=Reloj(),
            entorno=self.entorno,
            extractor=self.extractor,
            inspector=self.inspector,
            archivador=self.archivador,
            notificador=self.notificador if self.con_notificador else None,
            renderizador=self.renderizador,
            estado=self.estado,
            grupos=self.grupos,
            administrador=ADMIN,
            sin_registros=self.sin_registros,
            reintentos=PoliticaReintentos(intentos=3, espera_inicial_s=30, espera_maxima_s=120),
            version="0.1.0",
            dormir=self.esperas.append,
            nuevo_id=lambda: "abcdef1234",
        )
        return servicio.ejecutar(OpcionesEjecucion(modo, **opciones))  # type: ignore[arg-type]


def _estados(e: Ejecucion) -> dict[str, EstadoGrupo]:
    return {r.grupo: r.estado for r in e.resultados}


def _asuntos(esc: Escenario) -> list[str]:
    return [c.asunto for c in esc.notificador.enviados]


@pytest.fixture
def esc(tmp_path: Path) -> Escenario:
    return Escenario(tmp_path, {"Fisioterapeutas": [65], "Médicos": [40]})


def test_modo_prueba_todo_va_al_administrador(esc: Escenario) -> None:
    e = esc.ejecutar(Modo.PRUEBA)

    assert e.codigo_salida == 0
    assert _estados(e) == {"Fisioterapeutas": EstadoGrupo.ENVIADO, "Médicos": EstadoGrupo.ENVIADO}
    assert all(c.para == (ADMIN,) and not c.cc for c in esc.notificador.enviados)
    assert _asuntos(esc) == [
        "[PRUEBA] Reporte Fisioterapeutas",
        "[PRUEBA] Reporte Médicos",
        "Resumen 0 adjuntos",
    ]
    assert e.resultados[0].destinatarios == (ADMIN,)
    assert esc.extractor.abierto and esc.extractor.cerrado
    assert "TI" not in esc.extractor.exportados  # inactivo
    assert esc.estado.finalizada is e and esc.archivador.limpiezas == 1


def test_produccion_envia_a_jefe_y_copias(esc: Escenario) -> None:
    e = esc.ejecutar(Modo.PRODUCCION)

    jefe = esc.notificador.enviados[0]
    assert jefe.para == ("fisio@x.co",) and jefe.cc == ("cc@x.co",)
    assert e.resultados[0].destinatarios == ("fisio@x.co", "cc@x.co")
    assert e.resultados[0].sha256 == "sha-Fisioterapeutas"
    assert esc.notificador.enviados[-1].para == (ADMIN,)


def test_idempotencia_en_produccion(esc: Escenario) -> None:
    esc.estado.enviados_produccion.add((SEMANA, "Fisioterapeutas"))

    e = esc.ejecutar(Modo.PRODUCCION)

    assert _estados(e)["Fisioterapeutas"] is EstadoGrupo.OMITIDO_YA_ENVIADO
    assert esc.extractor.exportados == ["Médicos"]
    assert e.codigo_salida == 0


def test_forzar_reenvia(esc: Escenario) -> None:
    esc.estado.enviados_produccion.add((SEMANA, "Fisioterapeutas"))

    e = esc.ejecutar(Modo.PRODUCCION, forzar=True)

    assert _estados(e)["Fisioterapeutas"] is EstadoGrupo.ENVIADO


def test_idempotencia_no_aplica_en_prueba(esc: Escenario) -> None:
    esc.estado.enviados_produccion.add((SEMANA, "Fisioterapeutas"))

    e = esc.ejecutar(Modo.PRUEBA)

    assert _estados(e)["Fisioterapeutas"] is EstadoGrupo.ENVIADO


def test_todo_ya_enviado_no_abre_el_navegador(esc: Escenario) -> None:
    esc.estado.enviados_produccion |= {(SEMANA, "Fisioterapeutas"), (SEMANA, "Médicos")}

    esc.ejecutar(Modo.PRODUCCION)

    assert not esc.extractor.abierto


def test_dry_run_no_envia_ningun_correo(esc: Escenario) -> None:
    e = esc.ejecutar(Modo.DRY_RUN)

    assert set(_estados(e).values()) == {EstadoGrupo.VALIDADO_SIN_ENVIO}
    assert esc.notificador.enviados == []
    assert esc.archivador.archivados == ["Fisioterapeutas", "Médicos"]


def test_fallo_parcial_con_reintentos(tmp_path: Path) -> None:
    esc = Escenario(
        tmp_path,
        {
            "Fisioterapeutas": [ErrorCaptura("no apareció"), ErrorExtraccion("timeout"), 65],
            "Médicos": [ErrorExtraccion("x"), ErrorExtraccion("y"), ErrorExtraccion("selector")],
        },
    )

    e = esc.ejecutar(Modo.PRUEBA)

    fisio, medicos = e.resultados
    assert fisio.estado is EstadoGrupo.ENVIADO and fisio.intentos == 3
    assert medicos.estado is EstadoGrupo.FALLIDO and medicos.intentos == 3
    assert medicos.error == "selector"
    assert medicos.evidencias[0].name == "abcdef12_Medicos.png"
    assert esc.esperas == [30, 60, 30, 60]  # backoff exponencial por grupo
    assert e.codigo_salida == 1
    assert _asuntos(esc)[-1] == "Resumen 1 adjuntos"


def test_error_no_reintentable(tmp_path: Path) -> None:
    esc = Escenario(
        tmp_path, {"Fisioterapeutas": [ErrorPeriodoNoCoincide("otro rango")]}, grupos=(FISIO,)
    )

    e = esc.ejecutar(Modo.PRUEBA)

    assert e.resultados[0].intentos == 1 and esc.esperas == []
    assert e.resultados[0].error == "otro rango"


def test_validacion_fallida_no_envia(esc: Escenario) -> None:
    esc.inspector.periodo_texto = "2026-10-05 - 2026-10-11"

    e = esc.ejecutar(Modo.PRUEBA)

    assert set(_estados(e).values()) == {EstadoGrupo.FALLIDO}
    assert "periodo del Excel" in (e.resultados[0].error or "")
    assert _asuntos(esc) == ["Resumen 0 adjuntos"]
    assert esc.archivador.archivados == []


def test_sin_registros_omitir_y_reportar(tmp_path: Path) -> None:
    esc = Escenario(tmp_path, {"Fisioterapeutas": [0]}, grupos=(FISIO,))

    e = esc.ejecutar(Modo.PRUEBA)

    assert e.resultados[0].estado is EstadoGrupo.OMITIDO_SIN_REGISTROS
    assert _asuntos(esc) == ["Resumen 0 adjuntos"]
    assert e.codigo_salida == 0


def test_sin_registros_enviar_aviso(tmp_path: Path) -> None:
    esc = Escenario(
        tmp_path,
        {"Fisioterapeutas": [0]},
        grupos=(FISIO,),
        sin_registros=PoliticaSinRegistros.ENVIAR_AVISO,
    )

    e = esc.ejecutar(Modo.PRODUCCION)

    assert e.resultados[0].estado is EstadoGrupo.ENVIADO
    assert esc.notificador.enviados[0].asunto == "Sin registros Fisioterapeutas"


def test_error_fatal_de_entorno(esc: Escenario) -> None:
    esc.entorno.lista = ["HCWebControl no escucha"]

    e = esc.ejecutar(Modo.PRUEBA)

    assert e.codigo_salida == 2
    assert e.error_fatal == "HCWebControl no escucha"
    assert not esc.extractor.abierto
    assert {r.error for r in e.resultados} == {"no se procesó"}
    assert _asuntos(esc) == ["Resumen 0 adjuntos"]  # el administrador recibe la alerta


def test_login_rechazado_es_fatal(esc: Escenario) -> None:
    esc.extractor.error_abrir = ErrorLogin("HikCentral rechazó el inicio de sesión")

    e = esc.ejecutar(Modo.PRUEBA)

    assert e.codigo_salida == 2 and "rechazó" in (e.error_fatal or "")


def test_fatal_a_mitad_detiene_y_cierra_sesion(esc: Escenario) -> None:
    esc.notificador.fallar["Reporte Fisioterapeutas"] = ErrorCredenciales("sin clave SMTP")

    e = esc.ejecutar(Modo.PRODUCCION)

    assert e.codigo_salida == 2
    assert esc.extractor.exportados == ["Fisioterapeutas"]
    assert esc.extractor.cerrado
    assert _estados(e) == {"Fisioterapeutas": EstadoGrupo.FALLIDO, "Médicos": EstadoGrupo.FALLIDO}


def test_fallo_de_envio_de_un_grupo(esc: Escenario) -> None:
    esc.notificador.fallar["Reporte Médicos"] = ErrorNotificacion("buzón lleno")

    e = esc.ejecutar(Modo.PRODUCCION)

    assert _estados(e) == {"Fisioterapeutas": EstadoGrupo.ENVIADO, "Médicos": EstadoGrupo.FALLIDO}
    assert e.resultados[1].error == "no se envió: buzón lleno"
    assert e.resultados[1].archivo == "Asistencia_Medicos.xlsx"
    assert e.codigo_salida == 1


def test_resumen_no_enviado_da_codigo_1(esc: Escenario) -> None:
    esc.notificador.fallar["Resumen"] = ErrorNotificacion("smtp caído")

    e = esc.ejecutar(Modo.PRUEBA)

    assert e.codigo_salida == 1 and "smtp caído" in (e.error_resumen or "")


def test_sin_notificador(esc: Escenario) -> None:
    esc.con_notificador = False

    e = esc.ejecutar(Modo.PRUEBA)

    assert e.codigo_salida == 2 and "notificador" in (e.error_fatal or "")


def test_error_inesperado_no_deja_sin_aviso(esc: Escenario) -> None:
    esc.extractor.error_abrir = ZeroDivisionError()

    e = esc.ejecutar(Modo.PRUEBA)

    assert e.error_fatal == "error inesperado: ZeroDivisionError"
    assert _asuntos(esc) == ["Resumen 0 adjuntos"]


def test_solo_un_grupo(esc: Escenario) -> None:
    e = esc.ejecutar(Modo.DRY_RUN, solo_grupos=("médicos",))

    assert list(_estados(e)) == ["Médicos"]


def test_grupo_desconocido_es_fatal(esc: Escenario) -> None:
    e = esc.ejecutar(Modo.DRY_RUN, solo_grupos=("TI",))  # inactivo

    assert e.codigo_salida == 2 and "TI" in (e.error_fatal or "")


def test_adjunto_con_nombre_limpio_aunque_el_historico_tenga_version(esc: Escenario) -> None:
    """El histórico puede guardar _v2 (reenvíos), pero el jefe siempre recibe el nombre acordado."""
    esc.ejecutar(Modo.PRUEBA)

    assert esc.renderizador.adjuntos == [
        "Asistencia_Fisioterapeutas_2026-10-12_al_2026-10-18.xlsx",
        "Asistencia_Medicos_2026-10-12_al_2026-10-18.xlsx",
    ]
