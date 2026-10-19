# DISCOVERY — Reconocimiento del equipo (Fase 0)

Fecha: 2026-10-19 · Alcance: solo lectura (no se inició sesión en HikCentral ni se cambió ninguna configuración).

## 1. Equipo

| Dato | Valor |
|---|---|
| Tipo | Equipo de escritorio con Windows |
| Windows | Windows 11 Pro, 64 bits |
| Idioma / cultura | es-ES |
| Zona horaria | `SA Pacific Standard Time` (UTC−5, equivale a `America/Bogota`) |
| Usuario | Usuario local de Windows; la terminal corre **sin elevar** (UAC) |
| Sesión de Windows | El usuario mantiene la sesión de consola abierta |
| Inicio de sesión automático | **No** (no hay inicio de sesión automático) |

## 2. Software de base

Estado al iniciar la Fase 0 y después de las instalaciones aprobadas el 2026-10-19:

| Herramienta | Al inicio | Ahora |
|---|---|---|
| Python | **No instalado.** `python.exe` es solo el alias de la Microsoft Store (exit 9009). No hay lanzador `py`. | **3.13.16**, gestionado por uv en `C:\Users\<usuario>\.uv\python\cpython-3.13.16-windows-x86_64-none\` (ver la corrección más abajo) |
| uv | No instalado | **0.13.1** (`winget --scope user --skip-dependencies`; el VC++ Redistributable ya está en System32) |
| git | No instalado | **2.55.0.windows.5** (`C:\Program Files\Git`, Git.Git vía winget) |
| winget | Disponible (v1.29.380) | — |

**Corrección (2026-10-19):** la app de Claude es MSIX y virtualiza `AppData`. La primera instalación de Python quedó en `...\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\uv\python`, invisible para la terminal del usuario y para el Programador de tareas.
- Python se reinstaló en **`C:\Users\<usuario>\.uv\python\cpython-3.13.16-windows-x86_64-none\`**, fuera de `AppData`.
- `.venv` apunta a esa ruta concreta.

Detalle en [ADR-0001](docs/adr/0001-ubicacion-y-python.md).
| Microsoft Edge | 155.0.4283.62 (`C:\Program Files (x86)\Microsoft\Edge\Application`) |
| Google Chrome | 155.0.8059.80 (`C:\Program Files\Google\Chrome\Application`) |
| WebView2 | 155.0.4283.62 |
| LibreOffice | 26.2.4.2 (`soffice` no está en el PATH; el bot no lo necesita) |

**Consecuencia:** Playwright puede usar el Edge o el Chrome instalados (`channel="msedge"` / `"chrome"`) sin descargar su propio Chromium.

## 3. HikCentral Access Control

| Dato | Valor |
|---|---|
| Producto | HikCentral AC, edición `Oversea` |
| Versión | **2.4** (registro de Windows y `VSM Servers\Product.xml`) |
| Instalación | `C:\Program Files (x86)\HikCentral Access Control\VSM Servers\` |
| Plugins relevantes | attendance.s 1.25.0 · report.s 1.15.0 · integration.s 1.18.0 · baseacs.s 1.27.0 |
| Servicios (todos Auto, LocalSystem) | BeeAgent, Nginx…Nginx5, PostgreSQL, SADPServer, STREAM (BeeStream Media), SYS (BeeSYS) |
| Web | `https://127.0.0.1/` responde **HTTP 200** (certificado autofirmado). |
| Base de datos | PostgreSQL local (no se tocó) |
| Cliente adicional | `HikCentralControlClient` en `%APPDATA%\HikCentral\Client` (arranca con el usuario) |

La versión que muestra "Acerca de" en la interfaz web queda **pendiente de confirmar en la Fase 1**, porque requiere iniciar sesión.

### 3.1 OpenAPI

- nginx tiene rutas para el gateway OpenAPI ("Artemis"): `/artemis`, `/artemis-portal`, `/artemis-web`.
  - El archivo `ssl\artemis.conf` está en modo `odslocal`, que redirige a `127.0.0.1:9019`.
- **Ningún proceso escucha en 9016–9019.** `GET /artemis/` responde 502 y `/artemis-portal/` y `/artemis-web/` responden 404.
- **Conclusión:** la OpenAPI **no está activa** en esta instalación. Habilitarla sería un cambio de configuración en HikCentral, que está fuera del alcance acordado.
  - Queda anotada como alternativa futura, más robusta que la automatización de la interfaz.
  - Requeriría aprobación y una cotización aparte.

## 4. Centro de descargas / Downloadcenter (hallazgo clave)

**Las exportaciones no las descarga el navegador.** Las escribe un componente local nativo:

| Dato | Valor |
|---|---|
| Componente | **HCWebControl** 3.0.0.801477 (build 2025-03-13), `C:\Program Files\HCWebControl\HCWebControlService.exe` |
| Cómo corre | Proceso del usuario `<usuario>`, en su sesión de Windows. Arranca al iniciar sesión (clave `HKLM\...\Run\HCWebControl`). También se registra el protocolo `HCWebControl://`. |
| Comunicación con la web | WebSocket en `127.0.0.1:15000` (rango configurado 15000–15004, `LocalServiceConfig.xml`) |
| **Ruta absoluta de Downloadcenter** | **`C:\Users\<usuario>\HCWebControlService\Downloadcenter\`** |
| Estructura | `<Nombre del reporte>_<AAAA_MM_DD_HH_MM_SS>\<Nombre del reporte>_<desde>_<hasta>.xlsx` |
| Ejemplo | `Registros de entradas y salidas_2026_10_16_12_35_38\Registros de entradas y salidas_2026-10-05_2026-10-11.xlsx` (10 432 B) |
| Ubicación personalizada | Los logs de HCWebControl muestran que todas las exportaciones fueron a la ruta anterior. No hay evidencia de una ruta personalizada configurada. **Confirmar en la interfaz durante la Fase 1, sin cambiarla.** |

Observaciones:
- La carpeta se crea con la hora de inicio de la exportación. El `.xlsx` apareció ~1 s después.
- Hay carpetas de otros reportes ("Primer y último informe de acceso", "Transacciones") **sin archivo dentro**. Pudieron fallar o el archivo se movió. El bot debe tolerar una carpeta creada sin archivo, con un timeout y un error claro.
- Logs del componente: `C:\Users\<usuario>\HCWebControlService\log\` (`WebControl.log`, `taskcontrol\DownloadCenter\*.log`). En ellos se ve el progreso de la tarea (`TaskProgressNotifyToWeb`) y la apertura de la carpeta (`OpenFileByFilePath`).

Implicaciones para la Fase 1 (por confirmar):
1. Probablemente `page.expect_download()` (estrategia a) **no se dispare**, porque el archivo no pasa por el navegador. La estrategia más probable es **(b), vigilar la carpeta Downloadcenter**.
2. Chromium y Edge deberían funcionar igual: el componente se conecta por WebSocket a localhost, no como plugin del navegador. Sí requiere que **HCWebControlService esté corriendo en la misma sesión de Windows**.
3. Lo anterior hace poco probable el modo "ejecutar tanto si el usuario inició sesión como si no" (sesión 0, sin HCWebControl). Lo más probable es **"solo cuando el usuario haya iniciado sesión"**.

## 5. Energía y disponibilidad

| Dato | Valor |
|---|---|
| Plan | Equilibrado |
| Suspender (corriente alterna) | **Nunca** |
| Hibernar (corriente alterna) | **Nunca** |
| Apagar pantalla | Nunca |
| Temporizadores de reactivación | Habilitados |
| Inicio rápido | Habilitado |
| Estados disponibles | S3, Hibernar, Inicio rápido |

Historial de los últimos 45 días (registro de eventos del Sistema):
- El equipo **permanece encendido 24/7**. No hay apagados diarios.
- Hay reinicios esporádicos a horas variables, varios de madrugada o de noche (compatibles con Windows Update).
- Hubo apagados inesperados ocasionales (posibles cortes de energía).
- Las horas activas de Windows Update no están configuradas.

**Riesgo:** después de un reinicio nadie inicia sesión automáticamente. Mientras `<usuario>` no inicie sesión, HCWebControl no corre y el bot no puede exportar.

## 6. Sesiones de HikCentral

**Pendiente.** Para saber si el inicio de sesión del bot cierra la sesión de otra persona con `admin` hay que iniciar sesión. Se probará en la Fase 1 con la contraseña tomada de `keyring`, coordinando con quien tenga la sesión abierta.

## 7. Fase 1: exploración de la interfaz (2026-10-19)

**Método:**
- El navegador integrado de la app de Claude no abre `https://127.0.0.1`. Por eso se usó un **Edge desechable con depuración remota** (`--remote-debugging-port=9222`, perfil en `exploracion/perfil-edge/`).
- **El usuario inició sesión** en ese Edge. Claude se conectó por CDP con `exploracion/cdp.py` y leyó solo controles (roles, textos, títulos).
- La contraseña de confirmación al exportar también la escribió el usuario.
- No se imprimieron filas de tablas.

### 7.1 Mapa de la interfaz y selectores candidatos

| Pantalla o paso | Control | Selector candidato |
|---|---|---|
| Login | Pestaña "Administración" (activa por defecto), "Autoservicio" | `get_by_role("tab", name="Administración")` |
| Login | Usuario (`#username`) y contraseña (`#password`) | `get_by_placeholder("Nombre de usuario")`, `get_by_placeholder("Contraseña")`. **El campo de usuario trae `readonly` (anti-autocompletado) hasta recibir el foco: hay que hacer clic antes de `fill`.** Así falló la primera corrida de la PoC (timeout de `fill`). |
| Login | Botón | `get_by_role("button", name="Iniciar sesión")` |
| Login | Idioma | `input` con valor "Español" (no se toca) |
| Menú superior | Pestañas Dispositivo · Persona · Control de acceso · **Asistencia** · … | `get_by_role("tab", name="Asistencia", exact=True)`. **Sin `exact` también coincide con la pestaña "Revisión de asistencia"** de la página de inicio (así falló la quinta corrida). Con una ventana angosta se colapsan en "…", así que se usa un viewport ≥ 1600 px. |
| Aviso | "Haga clic aquí para actualizar los datos…" con **OK** y "No vuelva a mostrar el aviso" | `button.refresh-know` (OK). **La casilla no se marca.** |
| Menú lateral | Submenú "Registro de asistencia" → **"Registros de entradas y salidas"** | `locator("ul.el-menu").get_by_text("Registros de entradas y salidas", exact=True)`. Alternativa: la clase `li.el-menu-item_attendanceStaffCommutingReport`. **Ojo:** hay un duplicado oculto en "visitados recientemente", y el `textContent` del `li` incluye un tooltip oculto, así que **no** sirve filtrar el `li` con una expresión regular anclada (así falló la segunda corrida de la PoC). |
| Reporte | Botones Exportar · Guardar diseño · Cargar diseño · Personas seleccionadas · Ordenar · Columna personalizada | `button.export-btn`. **No tocar** Guardar diseño ni Columna personalizada. |
| Reporte | Periodo: Hoy, Ayer, Semana actual, **Última semana**, Mes actual (por defecto), Mes anterior, Últimos 3 meses, Últimos 6 meses, Este año, **Personalizado** | `get_by_placeholder("Por favor, seleccione.")` visible (el primero) → `.el-select-dropdown__item` con texto exacto |
| Personas | Botón "Personas seleccionadas" → panel con árbol zTree (raíz General), "Incluir departamento secundario" (marcada), lista de personas con buscador, "Seleccionar todos" y **Aceptar** | Nodo `li[class*='level'] a[title='<departamento>']` (los `id` son UUID que cambian) → `label.el-checkbox` "Seleccionar todos" → `button[title='Aceptar']`. El botón cambia a **"22 personas seleccionadas"**. |
| Exportar | Panel lateral `role=dialog` "**Configuración a exportar**": Formato Excel (marcado) / PDF / CSV · Modo monitor "Predefinido" · Nombre de usuario (`admin`, prellenado) · **Confirmar contraseña** · Exportar · Vista previa · Cancelar | `locator("[role='dialog'][aria-label='Configuración a exportar']")` visible. **`get_by_role("dialog", name=…)` NO funciona**: `aria-labelledby="el-drawer__title"` apunta a un id repetido (así falló la cuarta corrida). Dentro del panel hay controles ocultos duplicados: `label[title='Excel']`, `get_by_placeholder("Predefinido")` y `get_by_placeholder("Contraseña")` siempre filtrados por visibles, y botones por `button[title='Exportar']`. **Se cierra si se hace clic fuera.** |
| Centro de descargas | Icono `img[title='Centro de descargas']` → pestañas Descargando y Completado, "**Ubicación de descarga personalizada**", "Eliminar todo" | No se abrió "Ubicación…" (podría cambiarla). **Nunca** se pulsa "Eliminar todo". |
| Usuario | Menú `admin` (al pasar el mouse): Cambiar contraseña · **Cerrar sesión** | `div[role=button][title='admin']` → `li.el-dropdown-menu__item` "Cerrar sesión" |

Árbol de departamentos: **General > Aux. Enfermería · Fisioterapeutas · Medicos · Personal de Apoyo · Secretarias · TI**.
**"Medicos" va sin tilde** en HikCentral, y la configuración debe usar ese nombre exacto.

### 7.2 API observada (solo lectura, para validar)

- `POST /ISAPI/Bumblebee/AttendancePlugin/V1/Record` es la consulta de la tabla.
  - Cuerpo: `RecordRequest{PageIndex, PageSize=100, QueryInfo{BeginTime, EndTime, PersonID[], RecordType=3}}`.
  - Respuesta: `Data{PageIndex, PageSize, NextPage (1 = hay más), RecordAllCount=-1, OnOffDutyRecord[]}`.
  - **La API no informa el total, y la interfaz tampoco lo muestra.** Para comparar con el Excel hay que recorrer las páginas y sumar.
  - El tamaño de página máximo es 100 (opciones 10/20/30/40/50/100).
- **"Última semana"** se envía como `BeginTime=2026-10-12T00:00:00-05:00` y `EndTime=2026-10-18T23:59:59-05:00`. Es lunes a domingo, igual al cálculo del bot.
- `POST /ISAPI/Bumblebee/Platform/V0/CheckPassword` verifica la contraseña de confirmación antes de exportar.
- La exportación misma no aparece como XHR del navegador: la hace HCWebControl.

### 7.3 Captura del archivo (prueba con Fisioterapeutas, Última semana)

| Observación | Resultado |
|---|---|
| Evento `download` de Playwright (estrategia a) | **No se disparó.** Tampoco apareció nada en `C:\Users\<usuario>\Downloads`. |
| Carpeta nueva en Downloadcenter (estrategia b) | `Registros de entradas y salidas_2026_10_19_17_07_21`, creada al exportar |
| Archivo | `Registros de entradas y salidas_2026-10-12_2026-10-18.xlsx` (9 756 B). Apareció 1,5 s después de la carpeta y quedó estable (3 sondeos de 0,5 s) 1,6 s después. |
| Validación | Hoja `Sheet1`; `Periodo: 2026-10-12 - 2026-10-18` en la fila 7; los 11 encabezados en la fila 8; departamentos = {`General>Fisioterapeutas`}; **65 filas = 65 registros de la consulta** (1 página) |

Decisión: [ADR-0002](docs/adr/0002-captura-por-carpeta.md).

### 7.4 Otros hallazgos

- **Los traces de Playwright guardan el texto de los `fill`**, así que grabarían la contraseña. Hay que pausar el tracing en el login y en la confirmación de la exportación, o no grabar trace en esos pasos.
- Abrir la pantalla de login en un contexto aislado del navegador **no** cierra la sesión existente.
- El Edge de exploración quedó con sesión iniciada. Se cierra al terminar la Fase 1.

## 8. Decisiones y pendientes

| # | Tema | Estado |
|---|---|---|
| 1 | Ubicación del proyecto | **Decidido:** `C:\Users\<usuario>\asistencia-bot`. `C:\Program Files\asistencia-bot` es de solo lectura para `<usuario>` sin elevar. La carpeta elegida no requiere permisos de administrador y está fuera de OneDrive (Escritorio y Documentos no están redirigidos). |
| 2 | Credenciales en texto plano | **Pendiente (usuario).** `C:\Program Files\asistencia-bot\.env.txt` (2 líneas, 41 B) es legible por todos los usuarios locales. No se leyó su contenido. Se reemplaza por `keyring` con `asistencia-bot credenciales configurar`, y después el usuario lo elimina. |
| 3 | Instalaciones | **Hecho**, con aprobación: uv, git y Python 3.13 (sección 2). |
| 4 | ¿El login del bot cierra otra sesión de `admin`? | **No.** La PoC inició sesión con `admin` en un navegador nuevo a las 17:30. Después, la sesión del Edge de exploración siguió válida en el servidor (consulta `Record` con `ErrorCode=0` y 65 registros). HikCentral admite sesiones simultáneas del mismo usuario. Igual se recomienda un usuario dedicado por mínimo privilegio y trazabilidad (ADR-0004). |
| 5 | "Ubicación de descarga personalizada" | El botón existe y no se abrió, para no arriesgar un cambio. Los logs de HCWebControl muestran que todas las exportaciones van a la ruta por defecto. |
| 6 | Rango personalizado en el filtro de fecha | **Sí existe** ("Personalizado"). Útil a futuro para recuperar semanas; no está en el alcance. |
| 7 | Exportación con más de 100 filas | Pendiente: PoC con `--periodo "Mes anterior"`, que debería superar 100 filas, comparando con la suma de páginas de la consulta |
| 8 | Funcionamiento headless | Pendiente: PoC con `--headless` |
| 9 | Contraseña en `keyring` | Pendiente: el usuario debe completar `credenciales configurar` |
| 10 | Datos del cliente (sección 7 del encargo: grupos, jefes, SMTP, hora, usuario dedicado) | Pendiente. No bloquea la Fase 1. |
