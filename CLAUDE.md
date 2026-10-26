# CLAUDE.md — asistencia-bot

Bot en Python que **cada lunes** exporta de HikCentral Access Control el reporte *Registros de entradas y salidas* de la semana anterior (lunes a domingo), **un Excel por grupo**. Envía cada archivo, sin modificarlo, al jefe del grupo, y manda al administrador un resumen con alertas. 

- Arquitectura completa: [`docs/arquitectura.md`](docs/arquitectura.md)
- Hallazgos del equipo: [`DISCOVERY.md`](DISCOVERY.md)
- Decisiones: [`docs/adr/`](docs/adr/)

## Estado del proyecto

| Fase | Estado |
|---|---|
| 0. Reconocimiento del equipo | Terminada (`DISCOVERY.md`) |
| 1. Prueba de concepto (login, exportar Fisioterapeutas, capturar el archivo, validar) | **Terminada y aprobada (2026-10-20).** La PoC funciona en modo visible y headless, con captura por carpeta, cierre de sesión y sin cerrar otras sesiones. Más de 100 filas: el Excel está completo y la paginación de la interfaz está rota (ADR-0005). ADRs 0001–0005. |
| 2. Construcción | **Terminada (2026-10-20).**<br>- Código completo según `docs/arquitectura.md`.<br>- 115 pruebas unitarias.<br>- ruff y `mypy --strict` en verde.<br>- Cobertura: dominio 100 %, servicios 95 %. |
| 3. Pruebas (integración: `--dry-run` de todos los grupos, luego `--modo prueba`) | **Terminada (2026-10-23).**<br>- `--dry-run` OK el 2026-10-20: 4 grupos validados (22/65/73/75 filas, una página cada uno), código 0, 79 s.<br>- Corregido antes: `recargar()` usaba `goto('#/')`, que solo cambia el hash; ahora usa `page.reload()`.<br>- `--modo prueba` OK el 2026-10-23: `verificar` todo OK; 4 grupos enviados (22/65/73/75), código 0, 88 s. Las muestras fueron al responsable de aprobación del cliente con un cambio puntual del administrador (`ASISTENCIA_BOT_ADMINISTRADOR__CORREO`, solo esa ejecución).<br>- Corregido después: el adjunto llevaba `_v2` cuando el histórico ya tenía otra copia; ahora siempre se llama `Asistencia_<Grupo>_<desde>_al_<hasta>.xlsx`.<br>- El cliente aprobó la producción el 2026-10-23. |
| 4. Tarea programada y puesta en producción | **En curso (2026-10-23).**<br>- Producción activada en `config/settings.toml` (`modo_por_defecto = "produccion"`, `produccion_habilitada = true`), con el administrador definitivo.<br>- Tareas registradas con `scripts/registrar_tarea.ps1`: *asistencia-bot - reporte semanal* (lunes 05:00) y *asistencia-bot - ensayo* (2026-10-24 05:00, modo prueba al correo de pruebas del usuario; se borra sola a los 7 días).<br>- Ensayo del 2026-10-24: código 0. **Primera producción el 2026-10-26: código 0, 4 grupos enviados (9/38/48/45 filas).**<br>- Hallazgo del 2026-10-26: HikCentral no tiene registros del 21 al 25/10 en ningún grupo. El cálculo de asistencia corrió, pero no llegaron marcaciones del lector. Es un problema de HikCentral o del dispositivo, no del bot, y lo revisa el cliente. Si se recuperan, se reenvía con `--forzar` antes del 2026-11-01.<br>- Desde entonces, el resumen avisa ("OK con alertas") cuando un día de lunes a sábado no tiene registros en ningún grupo leído (`Ejecucion.dias_sin_registros`). No frena el envío.<br>- Pendiente del usuario: inicio de sesión automático de Windows y horas activas de Windows Update (ver "Trampas"). |

**Regla de avance:** no se pasa a la fase siguiente sin mostrarle los hallazgos al usuario y recibir su visto bueno. Cada fase termina con un commit.

## Reglas obligatorias (acordadas con el cliente)

1. **Credenciales:**
   - Nunca pedir la contraseña en el chat ni escribirla en código, archivos, logs, commits o salida.
   - Solo se guardan con `asistencia-bot credenciales configurar`, que usa `getpass` y `keyring`; el usuario las escribe.
   - **Claude no inicia sesión en HikCentral ni escribe contraseñas reales.** Tampoco ejecuta scripts que lo hagan, como el PoC o `ejecutar` contra HikCentral real: los lanza el usuario. Para explorar la interfaz, el usuario inicia sesión y Claude navega después (ver "Explorar HikCentral").
   - Existe `C:\Program Files\asistencia-bot\.env.txt` con credenciales en texto plano. **No leerlo ni usarlo.** Lo borra el usuario.
2. **HikCentral es de solo lectura:**
   - No cambiar usuarios, horarios, departamentos, ruta de descarga ni nada de configuración. Exportar sí está permitido.
   - Cualquier cambio (ubicación de descarga personalizada, usuario dedicado, OpenAPI) se propone y espera aprobación.
3. **Correos:** la producción se aprobó el 2026-10-23. **Solo la tarea semanal** (o un `ejecutar` que lance el propio usuario) envía a los jefes. Toda prueba usa `--modo prueba` (solo al administrador, o a otro destinatario con `ASISTENCIA_BOT_ADMINISTRADOR__CORREO`) o `--dry-run`. Claude nunca provoca un envío a los jefes por su cuenta.
4. **Archivos:**
   - No borrar ni mover nada en `Downloadcenter` ni en carpetas que no haya creado el bot o Claude. Los exportados se **copian** a `salida/`.
   - Nada de borrados permanentes de archivos ajenos.
5. **Instalaciones y tareas programadas:** pedir permiso antes de instalar software (incluidos los navegadores de Playwright; hoy se usan Edge y Chrome instalados) y antes de crear tareas en el Programador de tareas.
6. **Datos personales (Ley 1581 de 2012):**
   - Los reportes tienen nombres, cédulas y horarios. Nunca van al repositorio, a los logs (en ningún nivel) ni a fixtures; en las pruebas se usan datos sintéticos.
   - Capturas y traces solo en local, con retención, y solo se envían al administrador.
   - Al inspeccionar un Excel real, reportar **solo** el nombre del archivo y el conteo de filas, nunca su contenido.
7. **Sesiones:** el usuario `admin` puede tener una sesión abierta por una persona. Hay que verificar si el login del bot la cierra; si es así, se recomienda un usuario dedicado.
8. **Git:**
   - Un commit por fase como mínimo, con mensajes claros en español.
   - El remoto es `origin` = `https://github.com/SebastianMH14/asistencia-bot`.
   - **Solo hacer push cuando el usuario lo pida.** Se hace desde la terminal del usuario, porque GitHub puede pedir autenticación y esa la hace él.
   - Nunca hacer push forzado.
   - **El repositorio es PÚBLICO.**
     - Autor de los commits: `SebastianMH14 <77866016+SebastianMH14@users.noreply.github.com>`, configurado en el repo.
     - Nunca escribir en archivos versionados el nombre del cliente, el nombre del equipo, el usuario de Windows, la versión exacta de HikCentral, puertos internos ni datos personales. En la documentación se usan `<usuario>` y "el cliente".
     - Antes de cada push, revisar el diff con eso en mente.
   - Solo se sube `main`. `refs/original/` guarda el historial previo al saneamiento (2026-10-20) y es **solo local**: nunca usar `git push --all` ni `--mirror`.

## Comandos

En PowerShell 5.1, desde `C:\Users\<usuario>\asistencia-bot`.

```powershell
# En cada llamada del shell de Claude: refrescar PATH (uv y git se instalaron después de abrir la app)
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

uv sync --frozen                         # instala dependencias según uv.lock
uv run --frozen pytest -q                # pruebas unitarias (excluye @pytest.mark.hikcentral)
uv run --frozen pytest -m hikcentral     # integración: solo a mano, la lanza el usuario
uv run --frozen ruff check               # lint
uv run --frozen ruff format              # formato (usar --check para verificar)
uv run --frozen mypy                     # mypy --strict sobre src/
uv run --frozen asistencia-bot --help
uv run --frozen asistencia-bot credenciales comprobar hikcentral -u admin   # no muestra la contraseña
uv run --frozen asistencia-bot verificar          # sin exportar: config, claves, SMTP, HikCentral, HCWebControl
uv run --frozen asistencia-bot estado             # últimas ejecuciones (estado.db)
# ejecutar (--dry-run / --modo prueba / --modo produccion) inicia sesión en HikCentral: lo lanza el USUARIO
# OJO: desde el 2026-10-23, `ejecutar` sin --modo es PRODUCCIÓN (envía a los jefes)
uv add <paquete> / uv add --dev <paquete>   # dependencias: siempre con uv, nunca pip directo

# Tarea programada: se registra desde la terminal del USUARIO (no desde el shell de Claude, ADR-0001)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\registrar_tarea.ps1 -WhatIf   # sin -WhatIf registra
Get-ScheduledTask | Where-Object TaskName -like 'asistencia-bot*' | Get-ScheduledTaskInfo  # próxima y última ejecución
Get-Content -Encoding UTF8 logs\tarea.log -Tail 20     # intentos de la tarea y sus códigos de salida
```

- PowerShell 5.1 no tiene `&&`, `||` ni `?:`. Se encadena con `;` o con `if ($?) { ... }`.
- `.venv\Scripts\asistencia-bot.exe` funciona sin `uv` en el PATH. La tarea programada lo lanza a través de `scripts\ejecutar_tarea.ps1`, que espera a HikCentral y HCWebControl y reintenta una vez ante el código 2.
- **Si el ejecutable está en uso** (por ejemplo, un `credenciales configurar` esperando en una terminal), `uv run` sin `--no-sync` falla al reinstalar el proyecto. En ese caso se usa `uv run --no-sync`.
- **Configuración real del equipo:** `config/settings.toml` y `config/grupos.yaml`, ignorados por git.
  - Desde el 2026-10-23 tienen `[smtp]` (Gmail), `[administrador]` (el definitivo, responsable del cliente) y jefes y copias de los 4 grupos activos, tomados del listado de áreas y líderes del cliente. TI y Personal de Apoyo están inactivos.
  - El listado de áreas (`*.xlsx` en la raíz) tiene cédulas de empleados: está ignorado por git y **nunca** se imprime fila por fila; solo agregados.
  - Desde el 2026-10-23: `modo_por_defecto = "produccion"` y `produccion_habilitada = true` (aprobación del cliente). Para desactivar la producción: `produccion_habilitada = false` y `modo_por_defecto = "prueba"`, o deshabilitar la tarea.
  - El lanzador `Probar bot asistencia.cmd` del Escritorio (no versionado) corre `--modo prueba` y manda todo al correo de pruebas del usuario, no al administrador.

## Trampas de este equipo (leer antes de instalar o ejecutar)

- **La app de Claude es MSIX y virtualiza `AppData`.**
  - Lo que el shell de Claude escribe en `%APPDATA%` o `%LOCALAPPDATA%` termina en `C:\Users\<usuario>\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\...`. **El usuario y el Programador de tareas no lo ven.**
  - **Python del proyecto:** `C:\Users\<usuario>\.uv\python\cpython-3.13.16-windows-x86_64-none\` (ADR-0001). Instalar con `uv python install 3.13 --install-dir C:\Users\<usuario>\.uv\python`.
  - **Nunca** instalar herramientas en `AppData` desde el shell de Claude. Si algo tiene que quedar en el `AppData` real, se ejecuta en la terminal del usuario (`run_in_terminal`).
  - Las uniones (junctions) dentro del `AppData` virtualizado no se pueden atravesar. Por eso `.venv` se crea con la ruta concreta del intérprete:
    `uv venv --clear --python C:\Users\<usuario>\.uv\python\cpython-3.13.16-windows-x86_64-none\python.exe`
- **El shell no está elevado.** `C:\Program Files\...` no se puede escribir; por eso el proyecto vive en `C:\Users\<usuario>\asistencia-bot`.
- **Pestañas de terminal del usuario** (`run_in_terminal`): son su shell real, fuera del sandbox. `getpass` funciona ahí. No aceptan pipes, variables ni `$()`: para algo complejo se escribe un `.ps1` y se ejecuta con `powershell -NoProfile -ExecutionPolicy Bypass -File ...`.
- **El navegador integrado de la app no abre `https://127.0.0.1`.** Hay que usar el Edge de exploración (abajo).
- **uv y git:**
  - uv está en `C:\Users\<usuario>\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_...\uv.exe` (instalado con winget; es real, no virtualizado).
  - git está en `C:\Program Files\Git`.
- La zona horaria es `SA Pacific Standard Time`, equivalente a `America/Bogota`. La cultura es es-ES.
- **La tarea programada solo corre con la sesión de `<usuario>` iniciada**, porque HCWebControl vive en esa sesión.
  - Tras un reinicio (Windows Update, corte de luz) sin inicio de sesión automático, el lunes no corre hasta que alguien inicie sesión. Ahí corre sola ("lo antes posible si se omitió"), y nadie recibe aviso mientras tanto.
  - Inicio de sesión automático y horas activas de Windows Update son configuración del sistema: los cambia el usuario, no Claude.
- Los `.ps1` de `scripts/` se guardan en UTF-8 **con BOM**; sin BOM, PowerShell 5.1 los lee en ANSI y estropea las tildes.

## HikCentral: datos de referencia

- **Versión:** HikCentral Access Control **2.4** (Oversea). La web está en `https://127.0.0.1/#/` (nginx :443, certificado autofirmado).
- **Ruta del reporte:** Asistencia → Registro de asistencia → **Registros de entradas y salidas**.
- **Flujo manual:**
  1. *Personas selec.* → árbol bajo **General** → marcar el grupo → *Aceptar*.
  2. Periodo **"Última semana"**.
  3. *Exportar* → formato **Excel** → modo **Predefinido** → *Confirmar contraseña* → *Exportar*.
- **Grupos:**
  - Aux. Enfermería, Fisioterapeutas (22 personas), Médicos y Secretarias.
  - En el árbol de HikCentral **"Medicos" va sin tilde**, así que `departamento_hik: Medicos`.
  - Personal de Apoyo está **excluido** (vacío).
  - TI: **[Cliente]** falta confirmar.
- **Las exportaciones las escribe HCWebControl**, no el navegador:
  - Programa: `C:\Program Files\HCWebControl\HCWebControlService.exe`.
  - Corre como proceso de `<usuario>` y arranca al iniciar sesión. Habla con la web por WebSocket en `127.0.0.1:15000`.
  - Destino: `C:\Users\<usuario>\HCWebControlService\Downloadcenter\<Reporte>_<AAAA_MM_DD_HH_MM_SS>\<Reporte>_<desde>_<hasta>.xlsx`.
  - Logs: `C:\Users\<usuario>\HCWebControlService\log\`.
- **Excel exportado:**
  - Filas 1–3 vacías.
  - Fila 4: título.
  - Fila 5: `Hora de exportación:`.
  - Fila 6: `Operador:`.
  - Fila 7: `Periodo: AAAA-MM-DD - AAAA-MM-DD`.
  - Fila 8: encabezados (Nombre · Apellido · ID · Departamento · Fecha · Semana · Periodo de tiempo · Hora de registro de entrada · Salida a · Duración · Duración total).
  - El departamento viene como `General>Fisioterapeutas`.
  - **No depender de números de fila:** buscar `Periodo:` y la fila de encabezados.
- **OpenAPI:** no está activa (`/artemis` → 502). Está fuera de alcance; solo es una alternativa futura.
- **Consulta de la tabla:** `POST /ISAPI/Bumblebee/AttendancePlugin/V1/Record`, páginas de 100 como máximo, `NextPage` 1/0 y `RecordAllCount=-1`.
  - **Ni la interfaz ni la API dan el total.**
  - **La paginación está rota:** con más de dos páginas, la página 2 trae `PageSize+1` y `NextPage=0`.
  - El Excel sale completo. Validación según ADR-0005: con una página, igualdad; con varias, las claves (EmployeeID, Date) de la consulta deben estar contenidas en el Excel.
  - "Última semana" se envía como lunes 00:00 a domingo 23:59:59 en hora -05:00.
  - Cada registro trae `BaseInfo.Date` (fecha) y `BaseInfo.PersonInfo.EmployeeID`, que equivale a la columna "ID" del Excel.
- **Selectores frágiles ya resueltos** (detalle en `DISCOVERY.md` §7.1):
  - La pestaña "Asistencia" se busca por texto exacto dentro de `[role=tab].el-tabs__item`, no con `get_by_role(name=…)`.
  - El `#username` del login trae `readonly` hasta el foco: hay que hacer clic antes de `fill`.
  - Para el menú se usa `get_by_text(exact=True)`, porque el `li` tiene un tooltip oculto.
  - El panel de exportación se busca por CSS `aria-label`, con los controles filtrados por visibles.
- **La sesión expira por inactividad:** aparece la notificación `.session-expire-notification` ("Inicie sesión de nuevo.").
- **El evento `download` de Playwright no se dispara al exportar** (lo hace HCWebControl). Se vigila la carpeta (ADR-0002).
- **Los traces de Playwright guardan el texto de los `fill`.** Nunca hay que grabar trace durante el login ni durante la confirmación de la exportación.

## Explorar HikCentral (Fase 1)

1. El usuario abre un Edge desechable con depuración local, desde su terminal:
   ```powershell
   & 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' --remote-debugging-port=9222 --user-data-dir=C:\Users\<usuario>\asistencia-bot\exploracion\perfil-edge --no-first-run --no-default-browser-check https://127.0.0.1/#/
   ```
2. El **usuario** acepta el certificado e inicia sesión. Claude nunca escribe la contraseña.
3. Claude se conecta con `playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")` desde scripts en `exploracion/` y lee solo los controles (roles, nombres y textos).
   - **No vuelca tablas con datos de personas.** Si hace falta un conteo, se cuenta sin imprimir el contenido.
   - En el diálogo de exportar, el usuario escribe la contraseña de confirmación.
4. Al terminar: cerrar ese Edge. `exploracion/perfil-edge/` está en `.gitignore` porque guarda cookies de sesión.

**Herramientas de `exploracion/`:**
- **`cdp.py`**: explorador sobre CDP. Comandos `estado`, `controles`, `clic`, `clic-texto`, `clic-con-red`, `arbol`, `conteo-tabla`, `vigilar-exportacion`, `login-controles`, etc. Nunca imprime filas de tablas.
- **`validar_excel.py`**: estructura de un `.xlsx` (periodo, encabezados, departamentos, conteo, SHA-256), sin datos personales.
- **`poc_exportar.py`**: PoC completa. Login con keyring, grupo, periodo, conteo de páginas, exportación, captura y validación.
  - **La ejecuta el usuario**, nunca Claude, porque escribe la contraseña real en HikCentral.
  - No graba trace. Ante un error guarda una captura en `exploracion/salida/`.

## Arquitectura (resumen)

Es un hexágono ligero con inyección manual en `bootstrap.py`. Detalle en `docs/arquitectura.md`.

- `domain/` es Python puro: `Periodo`, `Grupo`, `MetadatosReporte`, `ResultadoGrupo`, `Ejecucion`, el cálculo de la semana anterior y las reglas de validación.
- `ports.py` tiene los `typing.Protocol`: `Reloj`, `AlmacenCredenciales`, `ExtractorAsistencia`, `InspectorReporte`, `Archivador`, `Notificador`, `RenderizadorCorreos` y `RepositorioEstado`.
- `services/ejecutar_reporte_semanal.py` orquesta extraer → validar → archivar → enviar → resumir, grupo por grupo. Aísla los fallos (un grupo que falla no detiene a los demás).
- `adapters/` contiene Playwright (`hikcentral/`), openpyxl, smtplib, sqlite3, keyring y jinja2.
- **Regla de dependencias:**
  - `domain/` y `services/` **no importan** Playwright, smtplib, keyring, openpyxl, jinja2 ni sqlite3.
  - Solo `bootstrap.py` instancia adaptadores.
  - `cli.py` traduce argumentos y códigos de salida (`0` OK, `1` fallo parcial, `2` fatal).

## Convenciones de código

- **Idioma:**
  - Identificadores, mensajes, docstrings, logs y commits en **español**. Los nombres de librerías y conceptos técnicos se dejan en inglés.
  - Los textos de la interfaz de HikCentral se escriben exactamente como aparecen, en español.
- **Tipos:**
  - Type hints completos; `mypy --strict` sobre `src/` sin errores ni `type: ignore` sin justificar.
  - En el dominio, `dataclass(frozen=True, slots=True)`.
  - Puertos como `Protocol`, sin herencia.
- **Docstrings:** breves y solo donde aportan (el porqué, no el qué).
- **Selectores de Playwright:**
  - Todos en `adapters/hikcentral/selectores.py`.
  - Usar `get_by_role(..., name=...)` y `get_by_text(...)` con texto en español. Nada de XPath frágil ni clases CSS autogeneradas.
- **Configuración:**
  - `pydantic` v2 + `pydantic-settings`. Ajustes en TOML y grupos en YAML.
  - Solo se versionan `config/*.example.*`. Los secretos, solo en `keyring`.
- **Excel:** `openpyxl` en `read_only=True` y **solo para validar**. El adjunto son los bytes originales, comprobados con SHA-256.
- **Zona horaria:** `zoneinfo.ZoneInfo("America/Bogota")` (requiere `tzdata` en Windows). Nada de `datetime.now()` sin zona: usar el puerto `Reloj`.
- **Logs:** registrar conteos, grupos, tiempos, identificadores de ejecución y hashes. **Jamás** nombres, cédulas, horarios individuales ni contraseñas.
- Mantenerlo **simple**: nada de frameworks de inyección, ORMs ni colas.

## Pruebas

- Las pruebas unitarias **nunca** tocan recursos reales:
  - **keyring:** un backend en memoria (`keyring.set_keyring`) o un almacén falso vía `monkeypatch` de `bootstrap.crear_almacen_credenciales`.
  - **SMTP y HikCentral:** fakes de los puertos.
  - **Excel:** se generan `.xlsx` **sintéticos** en `tests/fixtures/` con la misma estructura (encabezado en la fila 8, `Periodo:` en la fila 7, departamentos `General>X`).
- Las pruebas contra HikCentral real llevan `@pytest.mark.hikcentral`, quedan excluidas por defecto (`addopts`) y las lanza el usuario.
- **Metas:**
  - Cobertura ≥ 80 % en `domain/` y `services/`.
  - `ruff check`, `ruff format --check`, `mypy` y `pytest` en verde antes de cada commit.

## Pendiente de pedir al cliente (no inventar)

1. ~~¿TI recibe reporte?~~ No (2026-10-23).
2. ~~Jefe y copias de cada grupo~~ Definidos el 2026-10-23 (`config/grupos.yaml`).
3. ~~Correo definitivo del administrador~~ Definido el 2026-10-23 (`config/settings.toml`).
4. ~~Cuenta remitente~~ Gmail configurado; la contraseña de aplicación está en keyring.
5. ~~Hora del envío del lunes~~ 05:00 (2026-10-23).
6. ~~¿Usuario de HikCentral dedicado al bot o `admin`?~~ Se sigue con `admin` (2026-10-23).
