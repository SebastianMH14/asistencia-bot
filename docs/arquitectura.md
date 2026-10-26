# Arquitectura — asistencia-bot

> **Estado:** Fases 0–2 terminadas (reconocimiento, prueba de concepto y construcción). Fase 3 (pruebas de integración) pendiente.
> Lo marcado **[F1]** depende de la prueba de concepto y se cierra con un ADR en `docs/adr/`.
> Lo marcado **[Cliente]** depende de datos que debe entregar el cliente.
> Los hallazgos del equipo están en [`DISCOVERY.md`](../DISCOVERY.md).

## Índice

1. [Propósito](#1-propósito)
2. [Alcance](#2-alcance)
3. [Contexto del sistema](#3-contexto-del-sistema)
4. [Restricciones y hallazgos que condicionan el diseño](#4-restricciones-y-hallazgos-que-condicionan-el-diseño)
5. [Estilo arquitectónico](#5-estilo-arquitectónico)
6. [Modelo de dominio](#6-modelo-de-dominio)
7. [Puertos](#7-puertos)
8. [Adaptadores](#8-adaptadores)
9. [Flujo de una ejecución](#9-flujo-de-una-ejecución)
10. [Errores, reintentos y códigos de salida](#10-errores-reintentos-y-códigos-de-salida)
11. [Configuración](#11-configuración)
12. [Archivos en tiempo de ejecución y retención](#12-archivos-en-tiempo-de-ejecución-y-retención)
13. [Logs y datos personales](#13-logs-y-datos-personales)
14. [Línea de comandos](#14-línea-de-comandos)
15. [Programación y operación](#15-programación-y-operación)
16. [Seguridad](#16-seguridad)
17. [Pruebas y calidad](#17-pruebas-y-calidad)
18. [Extensibilidad (diseñado, no implementado)](#18-extensibilidad-diseñado-no-implementado)
19. [Decisiones de arquitectura (ADR)](#19-decisiones-de-arquitectura-adr)
20. [Estructura del repositorio](#20-estructura-del-repositorio)

---

## 1. Propósito

Cada lunes, el bot:

1. Exporta de **HikCentral Access Control** el reporte *Registros de entradas y salidas* de la **semana anterior (lunes a domingo)**. Genera **un Excel por grupo** (departamento).
2. Envía cada archivo, **byte a byte como lo generó HikCentral**, al jefe del grupo, con copia configurable.
3. Envía al administrador un **resumen** de la ejecución y **alertas** si algo falla.

## 2. Alcance

| Incluido (según la cotización) | No incluido (el diseño queda listo, sin implementar) |
|---|---|
| Exportación por grupo, sin transformar los datos | Resúmenes por persona y cálculo de novedades |
| Validación del archivo, renombrado e histórico | Corrección de marcaciones |
| Correo a cada jefe con copia configurable | Cambios de configuración en HikCentral |
| Resumen y alertas al administrador, con reintentos | Reenvío de periodos arbitrarios |
| Programación semanal, pruebas y puesta en producción | Frecuencia diaria |
| Guía corta y documentación técnica | |

## 3. Contexto del sistema

Todo corre en un solo equipo Windows, el mismo donde está instalado HikCentral.

```
                    Programador de tareas de Windows
                    (lunes, usuario "<usuario>", sesión iniciada [F1])
                                  │ ejecuta .venv\Scripts\asistencia-bot.exe ejecutar
                                  ▼
 ┌──────────────────────────── asistencia-bot (Python 3.13) ────────────────────────────┐
 │  cli.py ──► bootstrap.py ──► services/ejecutar_reporte_semanal.py ──► domain/        │
 └──────┬──────────────────┬───────────────────┬────────────────┬──────────────┬────────┘
        │ Playwright       │ vigila carpeta    │ keyring        │ sqlite3      │ smtplib (STARTTLS)
        ▼                  │ [F1]              ▼                ▼              ▼
  Edge o Chromium          │          Administrador de     estado.db     Servidor SMTP [Cliente]
  (headless en producción) │          credenciales de             │
        │ HTTPS            │          Windows                     ▼
        ▼                  │                               Jefes de grupo y administrador
  HikCentral web           │
  https://127.0.0.1        │
  (nginx :443 → SYS)       │
        ▲                  │
        │ descarga         │
        │                  ▼
  HCWebControl ──escribe──► C:\Users\<usuario>\HCWebControlService\Downloadcenter\
  (proceso del usuario;   <Reporte>_<AAAA_MM_DD_HH_MM_SS>\<Reporte>_<desde>_<hasta>.xlsx
   la página web le habla
   por WebSocket 127.0.0.1:15000)
```

Puntos clave:
- **El navegador no descarga el Excel.** La página web le pide la exportación a **HCWebControl**, un componente local nativo (`C:\Program Files\HCWebControl`). HCWebControl escribe el archivo en `Downloadcenter`.
- HCWebControl arranca cuando `<usuario>` inicia sesión en Windows (clave `HKLM\...\Run`) y corre **en la sesión interactiva de ese usuario**.

## 4. Restricciones y hallazgos que condicionan el diseño

| # | Hallazgo o restricción | Consecuencia en el diseño |
|---|---|---|
| R1 | El Excel lo escribe HCWebControl en `Downloadcenter`; no pasa por el navegador. Comprobado en la F1: el evento `download` de Playwright **no** se dispara. | Se captura **vigilando la carpeta** ([ADR-0002](adr/0002-captura-por-carpeta.md), aceptada). |
| R2 | HCWebControl corre solo dentro de la sesión de Windows de `<usuario>`. | La tarea programada corre "solo cuando el usuario haya iniciado sesión" **[F1]**. `verificar` y `ejecutar` comprueban que el proceso esté vivo. |
| R3 | Tras un reinicio nadie inicia sesión solo (no hay inicio de sesión automático). | Si `<usuario>` no ha iniciado sesión, el bot no corre. La tarea usa "ejecutar lo antes posible si se omitió". El runbook documenta qué hacer. |
| R4 | HikCentral pide la contraseña al iniciar sesión **y** al exportar. | El extractor la pide al `AlmacenCredenciales` cada vez que la necesita. Nunca la registra ni la guarda en atributos de objetos de larga vida. |
| R5 | Certificado autofirmado en `127.0.0.1`. | `ignore_https_errors=True` en un contexto de navegador que **solo** puede navegar a `127.0.0.1`: una ruta de Playwright aborta cualquier otro host. |
| R6 | La tabla pagina de a 100 filas (máximo). **Ni la interfaz ni la API informan el total** (`RecordAllCount=-1`). Además, **la paginación está rota**: con más de dos páginas, la página 2 trae un registro de más y `NextPage=0`, así que el resto es inalcanzable. El Excel sí sale completo. | El extractor recorre las páginas y guarda en memoria las claves `(EmployeeID, Date)`. El validador aplica [ADR-0005](adr/0005-validacion-de-filas.md): con una página, igualdad exacta; con varias, toda clave de la consulta debe estar en el Excel y las filas del Excel deben ser ≥ la suma. |
| R7 | ~~El login del bot podría cerrar la sesión de una persona con `admin`.~~ **Descartado en la F1:** HikCentral admite sesiones simultáneas. La sesión sí expira por inactividad (notificación "Inicie sesión de nuevo."). | Se recomienda igual un **usuario dedicado** por mínimo privilegio (ADR-0004, **[Cliente]**). El extractor detecta `.session-expire-notification` o la pantalla de login, y vuelve a iniciar sesión una vez. |
| R8 | La OpenAPI de HikCentral no está activa. | Se automatiza la interfaz web. El puerto `ExtractorAsistencia` permite cambiar a OpenAPI sin tocar el servicio. |
| R9 | El equipo está encendido 24/7, con reinicios esporádicos y cortes de energía. | Idempotencia en SQLite y periodo calculado sobre la fecha de ejecución. Una ejecución tardía sigue enviando la semana anterior. |
| R10 | Los reportes tienen nombres, cédulas y horarios (Ley 1581 de 2012). | Sin datos personales en logs, repositorio ni fixtures. Capturas y traces solo en local, con retención y solo para el administrador. |
| R11 | No hay Microsoft Excel; el archivo se envía tal cual. | `openpyxl` en solo lectura y **solo para validar**. El adjunto son los bytes originales. |
| R12 | La app de Claude (MSIX) virtualiza `AppData` para los procesos que lanza. | El Python del proyecto vive en `C:\Users\<usuario>\.uv\python` (ADR-0001). Solo afecta al desarrollo con Claude. |

## 5. Estilo arquitectónico

Es un **hexágono ligero** (puertos y adaptadores), con inyección de dependencias manual en un único *composition root*. No se usan frameworks de inyección ni plugins.

```
  cli.py ──────────► bootstrap.py ──────────► adapters/*  (Playwright, openpyxl, smtplib,
    │  (parsea          (único lugar que          │          sqlite3, keyring, jinja2)
    │   argumentos,      instancia adaptadores)    │ implementan
    │   código de salida)                          ▼
    └──────────────► services/* ──────────────► ports.py  (typing.Protocol)
                         │
                         └──────────────────► domain/*  (Python puro)
```

Reglas de dependencia (se revisan en cada code review):

| Capa | Puede importar | No puede importar |
|---|---|---|
| `domain/` | Librería estándar (`dataclasses`, `datetime`, `enum`, `zoneinfo`) | `ports`, `services`, `adapters` y cualquier librería de terceros |
| `services/` | `domain`, `ports`, librería estándar | `adapters`, Playwright, `smtplib`, `keyring`, `openpyxl`, `jinja2`, `sqlite3` |
| `ports.py` | `domain`, `typing` | Todo lo demás |
| `adapters/` | `ports`, `domain`, librerías de terceros | `services`, `cli` |
| `bootstrap.py` | Todo, salvo `cli` | — |
| `cli.py` | `bootstrap`, `config`, `domain` (enums y modelos de resultado) | Adaptadores directamente |

## 6. Modelo de dominio

Todo vive en `domain/`. Son `dataclass(frozen=True, slots=True)` y enums, sin efectos secundarios.

### 6.1 Entidades y valores

| Tipo | Campos principales | Notas |
|---|---|---|
| `Periodo` | `desde: date`, `hasta: date` | Invariantes: `desde` es lunes y `hasta = desde + 6 días`. Expone `etiqueta()` → `"2026-10-12_2026-10-18"`, `texto_asunto()` → `"12/10 al 18/10/2026"` y `desde_texto_hik("2026-10-12 - 2026-10-18")`. |
| `Grupo` | `nombre`, `departamento_hik`, `activo`, `correo_jefe`, `nombre_jefe`, `cc: tuple[str, ...]` | `nombre` es el que se muestra (asunto, archivo). `departamento_hik` es el nodo del árbol en HikCentral (p. ej. `Fisioterapeutas`). |
| `ReporteExportado` | `grupo`, `ruta: Path`, `tamano_bytes`, `consulta: ConsultaInterfaz \| None` | Archivo recién capturado en `Downloadcenter`, con lo que mostró la consulta de la interfaz; todavía sin validar. |
| `MetadatosReporte` | `titulo`, `periodo_texto`, `encabezados: tuple[str, ...]`, `departamentos: frozenset[str]`, `filas: int`, `claves: frozenset[tuple[str, date]]` | Lo que el adaptador de Excel extrae. `claves` = (ID de empleado, fecha) **solo en memoria** para la regla de ADR-0005: nunca se registra, persiste ni envía, y `__repr__` la oculta. Sin nombres. |
| `ConsultaInterfaz` | `paginas: int`, `registros: int`, `periodo_consultado: Periodo`, `claves: frozenset[tuple[str, date]]` (y la propiedad `una_pagina`) | Lo que el extractor vio al recorrer la consulta de la tabla. Las mismas restricciones sobre `claves`. Si `periodo_consultado` no es el esperado, el grupo falla sin reintentos (`ErrorPeriodoNoCoincide`). |
| `ArchivoArchivado` | `ruta: Path`, `sha256: str`, `tamano_bytes` | Copia en `salida/`. |
| `Modo` (enum) | `PRODUCCION`, `PRUEBA`, `DRY_RUN` | |
| `EstadoGrupo` (enum) | `ENVIADO`, `VALIDADO_SIN_ENVIO`, `OMITIDO_SIN_REGISTROS`, `OMITIDO_YA_ENVIADO`, `FALLIDO` | `ENVIADO` incluye el envío en modo prueba (el modo queda en `Ejecucion`). |
| `ResultadoGrupo` | `grupo`, `estado`, `filas`, `destinatarios`, `sha256`, `error`, `intentos`, `duracion` | `error` es un mensaje técnico sin datos personales. |
| `Ejecucion` | `id` (UUID), `inicio`, `fin`, `modo`, `periodo`, `resultados`, `version_bot` | La propiedad `codigo_salida` aplica las reglas de la sección 10. |

### 6.2 Cálculo del periodo (`domain/periodo.py`)

La función es pura: recibe la fecha local (`America/Bogota`, que entrega el puerto `Reloj`) y devuelve la semana **anterior** a la semana de esa fecha.

```
lunes_actual = hoy - timedelta(days=hoy.weekday())
desde        = lunes_actual - timedelta(days=7)
hasta        = desde + timedelta(days=6)
```

| Fecha de ejecución | Periodo | Caso |
|---|---|---|
| lun 2026-10-19 | 2026-10-12 → 2026-10-18 | Normal |
| mar 2026-10-20 | 2026-10-12 → 2026-10-18 | Ejecución tardía (equipo apagado el lunes) |
| dom 2026-10-25 | 2026-10-12 → 2026-10-18 | Muy tardía: sigue siendo la semana anterior a la actual |
| lun 2027-01-04 | 2026-12-28 → 2027-01-03 | Cambio de año |
| lun festivo | Igual que un lunes normal | Los festivos no cambian la semana |

> **Riesgo conocido:** en la interfaz se elige "Última semana", que HikCentral calcula con su propio reloj.
> En la F1 se confirmó que la consulta envía `BeginTime=2026-10-12T00:00:00-05:00` y `EndTime=2026-10-18T23:59:59-05:00` (lunes a domingo), igual que nuestro cálculo. La exportación manual del viernes 2026-10-16 también fue lunes–domingo.
> Si alguna vez difieren, la fila `Periodo:` del Excel no coincide y el grupo **falla sin enviarse**. Así nunca se envía una semana equivocada.
> La interfaz **sí tiene "Personalizado"** (rango explícito). Queda como mejora futura: reenvío de periodos arbitrarios, fuera del alcance.

### 6.3 Reglas de validación (`domain/validacion.py`)

Son funciones puras que reciben `MetadatosReporte`, el `Periodo` esperado y el `Grupo`. Devuelven una lista de problemas; si la lista está vacía, el archivo es válido.

1. **Periodo:** `periodo_texto` debe ser igual a `"<desde> - <hasta>"` (formato ISO observado). Si no, **falla y no se envía**.
2. **Encabezados:** deben estar `Nombre`, `Apellido`, `ID`, `Departamento`, `Fecha`, `Hora de registro de entrada` y `Salida a`, sin importar el orden.
3. **Departamentos:** todos deben terminar en `>{departamento_hik}` (p. ej. `General>Fisioterapeutas`). Un departamento ajeno indica un filtro equivocado y el grupo **falla**.
4. **Filas** ([ADR-0005](adr/0005-validacion-de-filas.md)): si hay 0 filas se aplica la política de "sin registros" (sección 10).
   - **Consulta de una página:** las filas del Excel deben ser **iguales** a los registros de la consulta. Si no, el grupo **falla**.
   - **Consulta de varias páginas:** toda clave (ID, fecha) vista en la consulta debe estar en el Excel; si falta alguna, el Excel está truncado y el grupo **falla**. Además, filas del Excel ≥ suma de páginas; la diferencia se informa al administrador y no bloquea.

## 7. Puertos

Viven en [`src/asistencia_bot/ports.py`](../src/asistencia_bot/ports.py) como `typing.Protocol`. Este es el resumen de lo implementado en la Fase 2:

```python
class Reloj(Protocol):
    def ahora(self) -> datetime: ...                      # aware, America/Bogota

class AlmacenCredenciales(Protocol):
    def obtener(self, sistema: str, usuario: str) -> str | None: ...
    def guardar(self, sistema: str, usuario: str, secreto: str) -> None: ...
    def borrar(self, sistema: str, usuario: str) -> bool: ...

class VerificadorEntorno(Protocol):
    def problemas(self) -> list[str]: ...                 # HikCentral, HCWebControl, carpeta, claves

class ExtractorAsistencia(Protocol):
    def abrir(self) -> None: ...                          # navegador + login (ErrorLogin/ErrorEntorno)
    def exportar(self, grupo: Grupo, periodo: Periodo) -> ReporteExportado: ...  # incluye la consulta
    def guardar_evidencia(self, etiqueta: str) -> tuple[Path, ...]: ...  # captura + trace del fallo
    def cerrar(self) -> None: ...                         # cierra sesión y navegador; no lanza

class InspectorReporte(Protocol):
    def leer_metadatos(self, ruta: Path) -> MetadatosReporte: ...

class Archivador(Protocol):
    def archivar(self, origen: Path, periodo: Periodo, grupo: Grupo) -> ArchivoArchivado: ...
    def limpiar(self, ahora: datetime) -> int: ...          # solo archivos creados por el bot

class Notificador(Protocol):
    def enviar(self, correo: Correo) -> None: ...          # ErrorNotificacion tras reintentos

class RenderizadorCorreos(Protocol):
    def correo_jefe(self, grupo, periodo, archivo: ArchivoArchivado, nombre_adjunto: str) -> Correo: ...
    def correo_sin_registros(self, grupo, periodo) -> Correo: ...
    def correo_resumen(self, ejecucion: Ejecucion, para: str, adjuntos: Sequence[Path]) -> Correo: ...
    def redirigir_a_prueba(self, correo: Correo, administrador: str) -> Correo: ...  # [PRUEBA]
    def correo_alerta_lector(self, para, ahora, estado: EstadoLector | None, error) -> Correo: ...

class RepositorioEstado(Protocol):
    def iniciar_ejecucion(self, ejecucion: Ejecucion) -> None: ...
    def registrar_resultado(self, ejecucion: Ejecucion, resultado: ResultadoGrupo) -> None: ...
    def finalizar_ejecucion(self, ejecucion: Ejecucion) -> None: ...
    def ya_enviado(self, periodo: Periodo, grupo: str) -> bool: ...  # solo envíos de producción
    def ultimas_ejecuciones(self, n: int) -> list[Ejecucion]: ...

class FuenteEventos(Protocol):                  # vigilancia del lector (ADR-0006)
    def muestras(self) -> list[MuestraEventos]: ...    # ErrorLectura si no puede leer
```

## 8. Adaptadores

| Adaptador | Implementa | Tecnología | Estado |
|---|---|---|---|
| `adapters/credenciales_keyring.py` | `AlmacenCredenciales` | `keyring` → `WinVaultKeyring` | Existe |
| `adapters/hikcentral/*` | `ExtractorAsistencia` | Playwright síncrono | Existe |
| `adapters/descargas.py` | (lo usa el extractor) | `pathlib`, sondeo | Existe |
| `adapters/excel_validador.py` | `InspectorReporte` | `openpyxl` solo lectura | Existe |
| `adapters/archivador.py` | `Archivador` | `shutil`, `hashlib` | Existe |
| `adapters/correo_smtp.py` | `Notificador` | `smtplib` + `EmailMessage` + `tenacity` | Existe |
| `adapters/plantillas.py` | `RenderizadorCorreos` | `jinja2` | Existe |
| `adapters/estado_sqlite.py` | `RepositorioEstado` | `sqlite3` | Existe |
| `adapters/reloj.py` | `Reloj` | `zoneinfo` + `tzdata` | Existe |
| `adapters/log_eventos_hik.py` | `FuenteEventos` | lectura del log `EventStatistics.log` de HikCentral (ADR-0006) | Existe |
| `adapters/candado.py` | (lo usa `cli`/`bootstrap`) | `msvcrt.locking` sobre `ejecucion.lock` | Existe |
### 8.1 Extractor de HikCentral (`adapters/hikcentral/`)

- **`selectores.py`**: es el **único** lugar con selectores.
  - Se prefieren `get_by_role(..., name="…")` y `get_by_text("…")` con los textos en español de la interfaz.
  - No se usan XPath ni clases CSS autogeneradas.
  - Cada selector lleva un comentario con la pantalla donde aparece.
- **`sesion.py`**: lanza el navegador. Usa `channel="msedge"` o `"chrome"` (ADR-0003), porque se usan los navegadores instalados y no hace falta descargar Chromium.
  - El contexto se crea con `ignore_https_errors=True`, viewport ≥ 1600×900 (más angosto, el menú superior se colapsa en "…"), `locale="es-ES"` y una ruta que **aborta todo host distinto de `127.0.0.1`**.
  - Hace el login y lo repite **una vez** si aparece la pantalla de login a mitad de la ejecución. Al terminar, cierra sesión desde el menú del usuario → "Cerrar sesión".
  - Activa el tracing por grupo, pero solo guarda el archivo si hubo error.
  - **El tracing se pausa** (`tracing.stop_chunk()` / `start_chunk()`) alrededor del login y de la confirmación de la exportación, porque Playwright guarda en el trace el texto de los `fill` y quedaría la contraseña.
  - Cierra el aviso "Haga clic aquí para actualizar…" con **OK** (`button.refresh-know`), sin marcar "No vuelva a mostrar".
- **`paginas.py`**: Page Objects.
  - `PaginaLogin`: pestaña *Administración*, usuario, contraseña, *Iniciar sesión*.
  - `PaginaRegistrosEntradasSalidas`: menú *Asistencia → Registro de asistencia → Registros de entradas y salidas*, selector de periodo, botón *Exportar* y lectura del total.
  - `PanelSeleccionPersonas`: botón *Personas selec.*, árbol de departamentos, casilla del grupo, *Aceptar*.
  - `DialogoExportar`: formato *Excel*, modo *Predefinido*, *Confirmar contraseña*, *Exportar*.
  - `CentroDescargas`: estado de la tarea, solo lectura.
- **`extractor_ui.py`**: hace el flujo de un grupo: seleccionar el grupo, elegir el periodo, exportar y esperar el archivo con `descargas.py`. Devuelve un `ReporteExportado`.

### 8.2 Captura del archivo (`adapters/descargas.py`)

Se decidió vigilar la carpeta ([ADR-0002](adr/0002-captura-por-carpeta.md)). En la F1 el archivo tardó ~3 s desde el clic hasta quedar estable.

1. **Antes** de pulsar *Exportar*, toma una foto del contenido de `Downloadcenter`: subcarpetas y fecha de creación.
2. Después espera una carpeta nueva `Registros de entradas y salidas_<AAAA_MM_DD_HH_MM_SS>`, creada después del clic, que contenga `Registros de entradas y salidas_<desde>_<hasta>.xlsx`.
3. Considera el archivo **estable** cuando su tamaño no cambia en *N* sondeos seguidos y se puede abrir en solo lectura.
4. Si pasa el tiempo límite configurable (por defecto 120 s), lanza `ErrorCaptura`. El reintento queda a cargo del servicio.
5. **Nunca** mueve, renombra ni borra nada en `Downloadcenter`; solo **copia**. Se observaron carpetas de exportación vacías, así que el bot debe tolerarlas.

La alternativa (a), `page.expect_download()`, se descartó: el evento no se dispara porque el archivo no pasa por el navegador.

### 8.3 Inspector de Excel (`adapters/excel_validador.py`)

- Usa `openpyxl.load_workbook(ruta, read_only=True, data_only=True)` y lee solo la primera hoja.
- **No depende de números de fila fijos.**
  - Busca en las primeras ~30 filas la celda que empieza por `Periodo:`.
  - Toma como fila de encabezados la que contiene `Nombre` y `Departamento`.
- Las filas de datos son las que siguen a los encabezados hasta la primera fila vacía. Solo cuenta filas y recoge el **conjunto** de departamentos; no conserva nombres ni cédulas.

### 8.4 Correo (`adapters/correo_smtp.py`, `adapters/plantillas.py`)

- Usa `smtplib.SMTP(host, puerto)` con `starttls()` y login con la contraseña de `keyring` (`sistema="smtp"`). Host, puerto y usuario: **[Cliente]**.
- Arma un `EmailMessage` con alternativa en texto plano y HTML (`jinja2`, autoescape activado).
  - El adjunto son los **bytes originales**, con MIME `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- **Asunto del jefe:** `Reporte de asistencia – <Grupo> – semana del DD/MM al DD/MM/AAAA`.
  - El cuerpo es breve y sin datos personales.
  - Incluye la leyenda: `-`/`--` en "Salida a" = no marcó salida; la misma hora de entrada y salida = una sola marcación; en ambos casos la duración es `00:00`.
- **Modo prueba:** el servicio reemplaza **todos** los destinatarios por el correo del administrador.
  - Antepone `[PRUEBA]` al asunto.
  - Agrega al cuerpo a quién se habría enviado.
  - Este es el comportamiento por defecto hasta la aprobación explícita del cliente.
- **Reintentos** con `tenacity`, solo ante errores transitorios: `SMTPServerDisconnected`, `SMTPConnectError`, códigos 4xx y `TimeoutError`.
- **Cambio a Microsoft Graph:** basta un nuevo adaptador `correo_graph.py` que implemente `Notificador`.

### 8.5 Estado (`adapters/estado_sqlite.py`)

```sql
CREATE TABLE IF NOT EXISTS ejecuciones (
    id             TEXT PRIMARY KEY,          -- UUID
    inicio         TEXT NOT NULL,             -- ISO 8601 con zona
    fin            TEXT,
    modo           TEXT NOT NULL,             -- produccion | prueba | dry_run
    periodo_desde  TEXT NOT NULL,
    periodo_hasta  TEXT NOT NULL,
    codigo_salida  INTEGER,
    version_bot    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resultados (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ejecucion_id   TEXT NOT NULL REFERENCES ejecuciones(id),
    periodo_desde  TEXT NOT NULL,
    periodo_hasta  TEXT NOT NULL,
    grupo          TEXT NOT NULL,
    modo           TEXT NOT NULL,
    estado         TEXT NOT NULL,             -- EstadoGrupo
    destinatarios  TEXT,                      -- JSON: correos de trabajo de jefes y cc
    sha256         TEXT,
    filas          INTEGER,
    intentos       INTEGER NOT NULL,
    error          TEXT,                      -- técnico, sin datos personales
    fecha          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_resultados_envio
    ON resultados (periodo_desde, grupo, modo, estado);
```

- **Idempotencia:** `ya_enviado(periodo, grupo)` es verdadero si existe un resultado con `modo='produccion'` y `estado='ENVIADO'`. Los envíos de prueba **no** bloquean los de producción. `--forzar` ignora esta verificación.
- Usa el modo WAL y una transacción por resultado. Así, si el proceso se cae a mitad, lo ya enviado queda registrado.

### 8.6 Candado (`adapters/candado.py`)

- Abre `ejecucion.lock` y toma un bloqueo exclusivo no bloqueante con `msvcrt.locking`. Si otro proceso lo tiene, termina con el código **2** y el mensaje "ya hay una ejecución en curso".
- El bloqueo lo libera el sistema operativo cuando el proceso muere, así que **no quedan candados huérfanos**.

## 9. Flujo de una ejecución

```
cli.ejecutar(modo, grupo?, forzar, visible)
 ├─ cargar y validar configuración (pydantic)  ── inválida → código 2
 ├─ tomar candado                               ── ocupado → código 2
 ├─ periodo = semana_anterior(reloj.ahora().date())
 ├─ verificar precondiciones: credenciales en keyring, HikCentral responde,
 │  HCWebControl vivo                           ── falla → resumen de alerta y código 2
 ├─ servicio.ejecutar(periodo, grupos_activos[, filtro]):
 │    con extractor (una sesión, un contexto de navegador):
 │      para cada grupo, en orden y de forma secuencial:
 │        si ya_enviado y no forzar  → OMITIDO_YA_ENVIADO; continuar
 │        reintentar(tenacity, intentos y espera configurables):
 │          reporte   = extractor.exportar(grupo, periodo)
 │          metadatos = inspector.leer_metadatos(reporte.ruta_origen)
 │          problemas = validar(metadatos, periodo, grupo, total_en_pantalla)
 │        si filas == 0 → política "sin registros" (sección 10)
 │        archivo = archivador.archivar(...)    (copia a salida/ y calcula SHA-256)
 │        si dry_run → VALIDADO_SIN_ENVIO
 │        si no      → notificador.enviar(correo_jefe, destinatarios según el modo) → ENVIADO
 │        registrar_resultado(...)               (siempre, también si falla)
 │        si error final → guardar_evidencia() y FALLIDO; **continuar con el siguiente grupo**
 ├─ días de lunes a sábado sin registros en ninguno de los grupos leídos → alerta "OK con alertas"
 │  (festivo o lector sin marcaciones; no frena el envío ni cambia el código de salida)
 ├─ enviar correo de resumen al administrador, con capturas y traces si hubo fallos (máx. 15 MB)
 │  (en dry-run no se envía nada: la CLI imprime el resumen en la consola)
 ├─ archivador.limpiar() según la retención
 └─ código de salida = ejecucion.codigo_salida
```

## 10. Errores, reintentos y códigos de salida

| Situación | Tipo | ¿Reintenta? | Resultado |
|---|---|---|---|
| Configuración inválida, credencial ausente, candado ocupado | Fatal | No | Código **2** (con alerta si ya se puede enviar correo) |
| HikCentral no responde o HCWebControl no está corriendo | Fatal | No (la tarea programada puede reintentar) | Alerta al administrador y código **2** |
| Fallo de login (contraseña incorrecta) | Fatal | No: reintentar podría bloquear la cuenta | Alerta y código **2** |
| Sesión expirada a mitad de la ejecución | Recuperable | **Un** relogin | Continúa |
| Selector no encontrado, timeout de UI o el archivo no aparece | Del grupo | Sí, con `tenacity` (por defecto 3 intentos y espera exponencial de 30 a 120 s) | `FALLIDO` si se agotan los intentos |
| Periodo, departamentos o encabezados no coinciden | Del grupo | No: es determinista, reintentar no lo arregla | `FALLIDO`, no se envía |
| La consulta de la interfaz cubre otro rango (`ErrorPeriodoNoCoincide`) | Del grupo (`ErrorNoReintentable`) | No | `FALLIDO` antes de exportar |
| Error inesperado (bug) | Fatal | No | Alerta "error inesperado: <tipo>" al administrador; código **2** |
| Grupo sin registros | Política | — | `omitir_y_reportar` (por defecto): `OMITIDO_SIN_REGISTROS`. `enviar_aviso_sin_registros`: correo al jefe sin adjunto. |
| Error SMTP transitorio | Del grupo | Sí, dentro del adaptador | `FALLIDO` si se agotan los intentos |

**Código de salida** (lo usa el Programador de tareas):
- `0`: todos los grupos están `ENVIADO`, `VALIDADO_SIN_ENVIO`, `OMITIDO_YA_ENVIADO` u `OMITIDO_SIN_REGISTROS`.
- `1`: al menos un grupo quedó `FALLIDO` y al menos uno terminó bien (**fallo parcial**). También es `1` si fallaron todos los grupos pero la sesión de HikCentral funcionó.
- `2`: error fatal antes o fuera del ciclo de grupos.

## 11. Configuración

Se carga con `pydantic` v2 y `pydantic-settings`. Los ajustes van en TOML y los grupos en YAML.
- Solo se versionan los archivos `*.example.*`.
- Los reales (`config/settings.toml`, `config/grupos.yaml`) están en `.gitignore` porque tienen correos personales.
- **Los secretos nunca van en la configuración**: van en `keyring`.

`config/settings.example.toml` (propuesta):

```toml
[hikcentral]
url = "https://127.0.0.1/#/"
usuario = "admin"                 # [Cliente] recomendado: usuario dedicado al bot
navegador = "msedge"              # msedge | chrome  [F1]
headless = true
timeout_ui_s = 30
timeout_captura_s = 120
carpeta_descargas = 'C:\Users\<usuario>\HCWebControlService\Downloadcenter'

[ejecucion]
zona_horaria = "America/Bogota"
modo_por_defecto = "prueba"       # se cambia a "produccion" solo con aprobación del cliente
reintentos = 3
espera_inicial_s = 30
espera_maxima_s = 120
sin_registros = "omitir_y_reportar"   # | "enviar_aviso_sin_registros"

[rutas]
base = 'C:\Users\<usuario>\asistencia-bot'  # salida/, logs/, capturas/, traces/, estado.db

[retencion]
excel_dias = 180
logs_dias = 90
evidencias_dias = 90              # capturas y traces

[smtp]                            # [Cliente]
host = "smtp.office365.com"
puerto = 587
usuario = "bot@ejemplo.com"
remitente = "Reportes de asistencia <bot@ejemplo.com>"

[administrador]
correo = "admin@ejemplo.com"      # [Cliente]
```

`config/grupos.example.yaml` (propuesta; los datos son sintéticos):

```yaml
grupos:
  - nombre: Fisioterapeutas
    departamento_hik: Fisioterapeutas
    activo: true
    jefe: { nombre: "Jefe de ejemplo", correo: "jefe.fisio@ejemplo.com" }
    cc: ["coordinacion@ejemplo.com"]
  - nombre: Médicos
    departamento_hik: Medicos   # así, sin tilde, se llama el nodo en HikCentral
    activo: true
    jefe: { nombre: "Jefe de ejemplo", correo: "jefe.medicos@ejemplo.com" }
    cc: []
  - nombre: Personal de Apoyo
    departamento_hik: Personal de Apoyo
    activo: false          # vacío: excluido
  - nombre: TI
    departamento_hik: TI
    activo: false          # [Cliente] ¿recibe reporte?
```

La validación al cargar revisa varias cosas:
- Correos válidos.
- Nombres de grupo únicos.
- `departamento_hik` no vacío.
- Al menos un grupo activo.
- `modo_por_defecto` válido.

## 12. Archivos en tiempo de ejecución y retención

Todo cuelga de `rutas.base`.

| Ruta | Contenido | Retención |
|---|---|---|
| `salida/AAAA-MM-DD_AAAA-MM-DD/Asistencia_<Grupo>_<desde>_al_<hasta>.xlsx` | Copia exacta del Excel (mismo SHA-256 que el original) | 180 días |
| `logs/bot.jsonl` (+ rotados) | Log JSON | 90 días |
| `capturas/<ejecucion>_<grupo>.png` | Captura ante un error (**sensible**) | 90 días |
| `traces/<ejecucion>_<grupo>.zip` | Trace de Playwright ante un error (**sensible**) | 90 días |
| `estado.db` | SQLite | Permanente (es pequeño) |
| `ejecucion.lock` | Candado | — |

- `<Grupo>` en el nombre del archivo es un *slug* ASCII (`Aux. Enfermería` → `Aux_Enfermeria`), para que no haya problemas con los adjuntos en algunos clientes de correo.
- La limpieza solo borra archivos **dentro de estas carpetas** cuyo nombre cumple el patrón del bot. **Nunca toca `Downloadcenter`.**

## 13. Logs y datos personales

- Usa `logging` estándar.
  - **Archivo:** JSON por línea, con rotación de 5 MB × 10 archivos.
  - **Consola:** formato legible.
- **Campos permitidos:** `ts`, `nivel`, `ejecucion_id`, `evento`, `grupo` (nombre del departamento), `periodo`, `intento`, `filas`, `duracion_ms`, `sha256`, `codigo_salida` y `error` (tipo y mensaje técnico).
- **Nunca se registran:** nombres, apellidos, cédulas, horarios individuales ni contraseñas. Esto vale **en ningún nivel**, tampoco en DEBUG.
- Los mensajes de error de Playwright pueden incluir el texto de la página, así que se recortan y se filtran antes de registrarlos.
- Las capturas y los traces contienen datos personales. Solo se adjuntan al **correo del administrador**, nunca al de los jefes.

## 14. Línea de comandos

| Comando | Qué hace | Estado |
|---|---|---|
| `credenciales configurar <hikcentral\|smtp> -u USUARIO` | Pide la contraseña con `getpass` y la guarda en `keyring` | **Existe** |
| `credenciales comprobar <sistema> -u USUARIO` | Dice si existe, sin mostrarla | **Existe** |
| `credenciales borrar <sistema> -u USUARIO` | La elimina | **Existe** |
| `ejecutar` | Modo por defecto de la configuración (`prueba` hasta que se apruebe producción) | **Existe** |
| `ejecutar --modo produccion` | Envía a los jefes; exige `produccion_habilitada = true` y jefes en todos los grupos activos | **Existe** |
| `ejecutar --modo prueba` | Todos los correos van solo al administrador, marcados `[PRUEBA]` | **Existe** |
| `ejecutar --dry-run` | Exporta, valida y archiva; **no envía ningún correo** (ni el resumen, que se imprime en consola). No requiere SMTP. | **Existe** |
| `ejecutar --grupo "Fisioterapeutas"` | Solo ese grupo (repetible) | **Existe** |
| `ejecutar --forzar` | Ignora la idempotencia | **Existe** |
| `ejecutar --visible` | Navegador visible para depurar | **Existe** |
| `verificar` | Revisa configuración, credenciales, SMTP (conexión y login), que HikCentral responda, que HCWebControl escuche y que la carpeta sea escribible. **No exporta.** Código 0 o 2. | **Existe** |
| `estado [-n 10]` | Últimas ejecuciones y resultados por grupo | **Existe** |
| `vigilar-lector [--sin-correo]` | ¿Hoy llegaron marcaciones a HikCentral? Si no, alerta al administrador (ADR-0006). Código 0 hay, 1 no hay o no se pudo revisar, 2 no se pudo avisar | **Existe** |

`ejecutar` sin `--modo` usa el `modo_por_defecto` de la configuración. Era `prueba` hasta la aprobación del cliente (2026-10-23); desde entonces es `produccion`, que es lo que corre la tarea semanal.

## 15. Programación y operación

`scripts/registrar_tarea.ps1` registra la tarea. Lo ejecuta el usuario desde su propia terminal (ADR-0001) y acepta `-WhatIf`. Volver a ejecutarlo reemplaza la tarea.

| Ajuste | Valor |
|---|---|
| Nombre | `asistencia-bot - reporte semanal` |
| Disparador | Lunes a las 05:00 (`-Dia` y `-Hora` para cambiarlo) |
| Usuario | `<usuario>`, el mismo que guardó las credenciales: el Administrador de credenciales es por usuario |
| Seguridad | "Ejecutar solo cuando el usuario haya iniciado sesión" (R2): HCWebControl solo vive en esa sesión. No guarda la contraseña de Windows ni pide elevación. |
| Si se omitió | "Ejecutar la tarea lo antes posible si se omitió un inicio programado" |
| Energía | Despertar el equipo; no detener si pasa a batería |
| Límite | 2 horas; si ya hay una instancia corriendo, no se inicia otra |
| Acción | `powershell.exe -File scripts\ejecutar_tarea.ps1`, oculta, con "Iniciar en" = carpeta del proyecto |

`scripts/ejecutar_tarea.ps1` es lo que corre la tarea:

1. Espera hasta 15 min a que respondan HikCentral y HCWebControl. Cubre el caso en que la tarea arranca justo al iniciar sesión tras un reinicio. Si no responden, ejecuta igual para que el bot avise al administrador.
2. Ejecuta `asistencia-bot ejecutar` y guarda su salida en `logs\tarea\<fecha>.txt`.
3. Con código **2** (fatal), reintenta una vez a los 15 min. Con 0 o 1 no reintenta: el 1 ya llega al administrador y se corrige a mano (runbook §4).
4. Anota cada intento y su código en `logs\tarea.log`, y borra sus propias salidas de más de 90 días.

Antes de la primera ejecución real se puede registrar un **ensayo** (`-Ensayo '<fecha hora>' -CorreoEnsayo <correo>`). Es una ejecución única en modo prueba que manda todo a ese correo en lugar del administrador, y la tarea se borra sola a los 7 días.

**Vigilancia del lector** (ADR-0006). Hay una segunda tarea, `asistencia-bot - vigilancia del lector`:
- Corre de lunes a sábado a las 10:00 (`-HoraVigilancia`), con el mismo usuario y la misma seguridad que la semanal.
- Lanza `pythonw -m asistencia_bot vigilar-lector`, sin ventana, con un límite de 10 min.
- Si hoy no han llegado marcaciones a HikCentral, avisa al administrador el mismo día en vez del lunes siguiente.

**Límite conocido:** si el equipo se reinicia y nadie inicia sesión, la tarea no corre ni avisa. Se mitiga con el inicio de sesión automático de Windows (con bloqueo de pantalla) y con horas activas de Windows Update que cubran las 05:00.

La operación diaria (cambiar destinatarios, reenviar con `--forzar`, qué hacer ante cada código de salida) va en `docs/runbook.md`.

## 16. Seguridad

- **Credenciales:**
  - Solo en el Administrador de credenciales de Windows. Las entradas se llaman `asistencia-bot/hikcentral` y `asistencia-bot/smtp`.
  - Se piden con `getpass`. Nunca van en código, archivos, logs, commits ni salida de consola.
- **Navegador:**
  - `ignore_https_errors` se limita al único host permitido (`127.0.0.1`), con una ruta que aborta cualquier otro destino.
  - La depuración remota (CDP, puerto 9222) **solo** se usa en la exploración de la Fase 1, con un perfil desechable en `exploracion/perfil-edge/`, y nunca en producción.
- **HikCentral es de solo lectura para el bot:** no cambia configuración. Exportar no es un cambio de configuración.
- **Mínimo privilegio** (recomendación, ADR-0004): un usuario de HikCentral dedicado al bot, con permiso solo para consultar y exportar asistencia.
- **Repositorio:** el `.gitignore` excluye secretos, la configuración real, `salida/`, `logs/`, `estado.db`, capturas, traces y cualquier `.xlsx` o `.csv`. No hay remoto sin autorización.

## 17. Pruebas y calidad

| Nivel | Qué cubre | Cómo |
|---|---|---|
| Unitarias, `domain/` | Periodo (cambio de año, ejecución tardía, festivo) y reglas de validación | Funciones puras |
| Unitarias, adaptadores puros | Inspector de Excel con `.xlsx` **sintéticos** (OK, periodo distinto, departamento mezclado, sin filas, encabezados movidos), plantillas, archivador y SQLite | `tmp_path`; generador en `tests/fixtures/` |
| Unitarias, `services/` | Idempotencia, fallo parcial, modo prueba, dry-run, sin registros, relogin | *Fakes* de todos los puertos |
| CLI | Comandos y códigos de salida | `typer.testing.CliRunner` con fakes |
| Integración | `ejecutar --dry-run` y `ejecutar --modo prueba` contra HikCentral real | Marcadas `@pytest.mark.hikcentral`; excluidas por defecto; se corren a mano en este equipo |

Metas:
- Cobertura ≥ 80 % en `domain/` y `services/`.
- `ruff check`, `ruff format --check` y `mypy --strict` (sobre `src/`) sin errores.
- Las pruebas **nunca** tocan el Administrador de credenciales real, un SMTP real ni HikCentral, salvo las de integración.

## 18. Extensibilidad (diseñado, no implementado)

| Necesidad futura | Punto de extensión |
|---|---|
| Resúmenes por persona y novedades | Un nuevo caso de uso en `services/` y un puerto `LectorFilas` que devuelva filas tipadas. El dominio ya separa metadatos de contenido. |
| Reenvío de periodos arbitrarios | `Periodo` ya es un valor independiente. Faltan opciones `--desde/--hasta` en la CLI y que el extractor use el **rango personalizado** de la interfaz **[F1]**. |
| Frecuencia diaria | Cambiar `semana_anterior()` por una estrategia de periodo inyectable (`CalculadoraPeriodo`) y agregar otro disparador. |
| Microsoft 365 / Graph | Un nuevo adaptador `correo_graph.py` que implemente `Notificador`. |
| OpenAPI de HikCentral | Un nuevo adaptador `extractor_openapi.py` que implemente `ExtractorAsistencia`. El servicio no cambia. Requiere habilitar la OpenAPI (cambio de configuración, fuera de alcance). |

## 19. Decisiones de arquitectura (ADR)

| ADR | Decisión | Estado |
|---|---|---|
| [0001](adr/0001-ubicacion-y-python.md) | Ubicación del proyecto y Python fuera de `AppData` | Aceptada |
| [0002](adr/0002-captura-por-carpeta.md) | Captura del Excel vigilando Downloadcenter | Aceptada (confirmada en headless) |
| [0003](adr/0003-navegador-edge-headless.md) | Edge instalado (`channel="msedge"`), headless | Aceptada |
| [0004](adr/0004-usuario-hikcentral.md) | Usuario de HikCentral para el bot (recomendado: dedicado) | Propuesta [Cliente] |
| [0005](adr/0005-validacion-de-filas.md) | Validación de filas frente a la paginación rota de HikCentral | Aceptada |
| [0006](adr/0006-vigilancia-del-lector.md) | Vigilancia diaria del lector a partir del log de HikCentral | Aceptada |

## 20. Estructura del repositorio

```
asistencia-bot/
├─ CLAUDE.md, DISCOVERY.md, README.md
├─ pyproject.toml / uv.lock          dependencias (uv, Python 3.13)
├─ config/                           settings.example.toml, grupos.example.yaml (los reales no se versionan)
├─ docs/                             arquitectura.md, runbook.md, guia-cliente.md, adr/0001–0006
├─ exploracion/                      herramientas de la Fase 1 (no es código de producción)
├─ scripts/                          registrar_tarea.ps1 (registra las tareas), ejecutar_tarea.ps1 (lo que corre la semanal)
├─ src/asistencia_bot/
│  ├─ __main__.py, cli.py            ejecutar · verificar · estado · vigilar-lector · credenciales
│  ├─ bootstrap.py                   composition root
│  ├─ config.py, logging_config.py
│  ├─ ports.py
│  ├─ domain/                        modelos, errores, periodo, validacion, vigilancia
│  ├─ services/                      ejecutar_reporte_semanal.py, vigilar_lector.py
│  ├─ adapters/                      hikcentral/{selectores,paginas,sesion,extractor_ui}.py, descargas,
│  │                                 excel_validador, archivador, estado_sqlite, correo_smtp, plantillas,
│  │                                 entorno, candado, reloj, logs, credenciales_keyring, log_eventos_hik
│  └─ templates/                     correo_jefe, correo_sin_registros, correo_resumen, correo_alerta_lector
│                                    (.html.j2/.txt.j2)
└─ tests/
   ├─ unit/                          141 pruebas con fakes, Excel y logs sintéticos (sin recursos reales)
   ├─ integration/                   @pytest.mark.hikcentral (Fase 3)
   └─ fixtures/                      generador de Excel sintético
```