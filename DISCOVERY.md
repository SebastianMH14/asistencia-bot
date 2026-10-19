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
| Python | **No instalado.** `python.exe` es solo el alias de la Microsoft Store (exit 9009). No hay lanzador `py`. | **3.13.16**, gestionado por uv en `%APPDATA%\uv\python\cpython-3.13.16-windows-x86_64-none\` |
| uv | No instalado | **0.13.1** (`winget --scope user --skip-dependencies`; el VC++ Redistributable ya está en System32) |
| git | No instalado | **2.55.0.windows.5** (`C:\Program Files\Git`, Git.Git vía winget) |
| winget | Disponible (v1.29.380) | — |

Nota: uv crea la unión (junction) `cpython-3.13-windows-x86_64-none` hacia la instalación 3.13.16. La terminal aislada de desarrollo no puede atravesar uniones. Por eso el entorno virtual se crea con la ruta concreta del intérprete.
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

## 7. Decisiones y pendientes

| # | Tema | Estado |
|---|---|---|
| 1 | Ubicación del proyecto | **Decidido:** `C:\Users\<usuario>\asistencia-bot`. `C:\Program Files\asistencia-bot` es de solo lectura para `<usuario>` sin elevar. La carpeta elegida no requiere permisos de administrador y está fuera de OneDrive (Escritorio y Documentos no están redirigidos). |
| 2 | Credenciales en texto plano | **Pendiente (usuario).** `C:\Program Files\asistencia-bot\.env.txt` (2 líneas, 41 B) es legible por todos los usuarios locales. No se leyó su contenido. Se reemplaza por `keyring` con `asistencia-bot credenciales configurar`, y después el usuario lo elimina. |
| 3 | Instalaciones | **Hecho**, con aprobación: uv, git y Python 3.13 (sección 2). |
| 4 | ¿El login del bot cierra otra sesión de `admin`? | Pendiente: Fase 1 |
| 5 | Versión en "Acerca de" y "Ubicación de descarga personalizada" en la interfaz | Pendiente: Fase 1 (solo lectura) |
| 6 | Datos del cliente (sección 7 del encargo: grupos, jefes, SMTP, hora, usuario dedicado) | Pendiente. No bloquea la Fase 1. |
