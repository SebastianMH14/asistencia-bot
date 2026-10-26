# asistencia-bot

Bot que **cada lunes** exporta de **HikCentral Access Control** el reporte *Registros de entradas y salidas* de la **semana anterior (lunes a domingo)**, un Excel por grupo.
- Envía cada archivo **sin modificarlo** al jefe del grupo.
- Envía al administrador un resumen con alertas.

Se hizo a la medida para un cliente.

- Arquitectura: [`docs/arquitectura.md`](docs/arquitectura.md)
- Operación diaria: [`docs/runbook.md`](docs/runbook.md)
- Guía para el cliente: [`docs/guia-cliente.md`](docs/guia-cliente.md)
- Decisiones: [`docs/adr/`](docs/adr/)
- Hallazgos del equipo: [`DISCOVERY.md`](DISCOVERY.md)

## Cómo funciona

1. Inicia sesión en la web de HikCentral (`https://127.0.0.1`) con Edge sin ventana (headless).
2. Para cada grupo activo:
   1. Elige el departamento y "Última semana".
   2. Exporta en Excel (modo *Predefinido*).
   3. Toma el archivo que HCWebControl deja en `Downloadcenter`.
3. **Valida** el periodo, el departamento, los encabezados y las filas (regla de [ADR-0005](docs/adr/0005-validacion-de-filas.md)).
4. **Copia** el Excel byte a byte al histórico `salida/` y verifica el SHA-256.
5. Lo envía por correo al jefe. En modo prueba, solo al administrador.
6. Registra todo en `estado.db`, que evita reenvíos, y manda el resumen.

## Requisitos

- Windows 10/11 con **HikCentral Access Control 2.4** y su componente **HCWebControl**.
  - HCWebControl corre en la sesión del usuario de Windows, así que **ese usuario debe tener la sesión iniciada**.
- **Microsoft Edge**, que ya viene con Windows. No se descargan navegadores de Playwright.
- `git` y [`uv`](https://docs.astral.sh/uv/) (instalan Python 3.13).
- Una cuenta de correo para enviar (Microsoft 365 o Gmail) con SMTP habilitado.

## Instalación desde cero (otro equipo)

Todo con el **mismo usuario de Windows** que va a ejecutar la tarea programada, porque el Administrador de credenciales es por usuario.

1. Instala las herramientas, con permiso del administrador del equipo:

   ```powershell
   winget install --id Git.Git -e
   winget install --id astral-sh.uv -e
   ```

2. Clona el proyecto e instala sus dependencias. Abre una terminal nueva para que se actualice el PATH:

   ```powershell
   git clone https://github.com/SebastianMH14/asistencia-bot.git C:\Users\<usuario>\asistencia-bot
   cd C:\Users\<usuario>\asistencia-bot
   uv python install 3.13
   uv sync --frozen
   ```

   > Si se instala desde la app de escritorio de Claude, Python debe ir fuera de `AppData` (ver [ADR-0001](docs/adr/0001-ubicacion-y-python.md)).

3. Configura:

   ```powershell
   copy config\settings.example.toml config\settings.toml
   copy config\grupos.example.yaml config\grupos.yaml
   ```

   Edita los dos archivos. Ninguno se versiona, porque tienen correos.

4. Guarda las contraseñas. Se piden sin mostrarse y quedan en el Administrador de credenciales de Windows:

   ```powershell
   .venv\Scripts\asistencia-bot.exe credenciales configurar hikcentral -u admin
   .venv\Scripts\asistencia-bot.exe credenciales configurar smtp -u reportes@ejemplo.com
   ```

5. Verifica y prueba:

   ```powershell
   .venv\Scripts\asistencia-bot.exe verificar
   .venv\Scripts\asistencia-bot.exe ejecutar --dry-run      # exporta y valida, no envía nada
   .venv\Scripts\asistencia-bot.exe ejecutar --modo prueba  # todos los correos van al administrador
   ```

6. Programa la tarea semanal (lunes 05:00) desde tu propia terminal:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\registrar_tarea.ps1
   ```

   Detalles en [`docs/runbook.md`](docs/runbook.md) §10.

## Uso

| Comando | Qué hace |
|---|---|
| `asistencia-bot ejecutar` | Corre en el modo por defecto de la configuración (`prueba` hasta que se apruebe producción) |
| `asistencia-bot ejecutar --modo prueba` | Todos los correos van **solo al administrador**, marcados `[PRUEBA]` |
| `asistencia-bot ejecutar --modo produccion` | Envía a los jefes. Requiere `ejecucion.produccion_habilitada = true` |
| `asistencia-bot ejecutar --dry-run` | Exporta, valida y archiva; **no envía ningún correo**. El resumen sale en la consola |
| `asistencia-bot ejecutar --grupo "Fisioterapeutas"` | Solo ese grupo (se puede repetir) |
| `asistencia-bot ejecutar --forzar` | Reenvía aunque ese periodo ya se haya enviado en producción |
| `asistencia-bot ejecutar --visible` | Muestra el navegador (para depurar) |
| `asistencia-bot verificar` | Revisa configuración, contraseñas, SMTP, HikCentral, HCWebControl y carpetas, sin exportar |
| `asistencia-bot estado [-n 10]` | Últimas ejecuciones y resultado por grupo |
| `asistencia-bot vigilar-lector [--sin-correo]` | ¿Hoy llegaron marcaciones a HikCentral? Si no, avisa al administrador. La tarea diaria lo corre de lunes a sábado a las 10:00 |
| `asistencia-bot credenciales configurar\|comprobar\|borrar <hikcentral\|smtp> -u USUARIO` | Contraseñas en keyring |

**Códigos de salida de `ejecutar`:**

| Código | Significado |
|---|---|
| `0` | Todo OK |
| `1` | Fallos parciales: algún grupo falló o no se pudo enviar el resumen |
| `2` | Error fatal: configuración, contraseña, HikCentral, HCWebControl o ejecución en curso |

Qué hacer en cada caso: [`docs/runbook.md`](docs/runbook.md).

## Archivos que genera

Todos van dentro de `rutas.base` y ninguno se versiona:

| Ruta | Contenido | Retención |
|---|---|---|
| `salida/AAAA-MM-DD_AAAA-MM-DD/Asistencia_<Grupo>_<desde>_al_<hasta>.xlsx` | Copia exacta del Excel | 180 días |
| `logs/bot.jsonl` | Log en JSON, sin datos personales | 90 días |
| `capturas/`, `traces/` | Evidencias de fallos. **Sensibles**: solo para el administrador | 90 días |
| `estado.db` | Historial de ejecuciones y envíos (SQLite) | — |

## Datos personales y seguridad (Ley 1581 de 2012)

- **Contraseñas:** solo en el Administrador de credenciales de Windows. Nunca en archivos, logs ni commits.
- **Datos de los reportes:** nombres, cédulas y horarios no van al repositorio, a los logs ni a las pruebas, que usan Excel sintéticos.
- **El bot no cambia ninguna configuración de HikCentral:** solo consulta y exporta.
- **Navegador:**
  - Solo puede comunicarse con `127.0.0.1`; se bloquea cualquier otro host.
  - El *trace* de depuración se pausa antes de escribir la contraseña de confirmación.

## Desarrollo

```powershell
uv sync --frozen
uv run pytest -q --cov=asistencia_bot   # pruebas unitarias (sin HikCentral, SMTP ni keyring reales)
uv run ruff check; uv run ruff format --check
uv run mypy                             # --strict sobre src/
```

- **Arquitectura:** hexágono ligero.
  - `domain/` y `services/` no dependen de Playwright, SMTP ni keyring.
  - Los adaptadores se conectan en `bootstrap.py`.
- **Selectores de HikCentral:** todos en `src/asistencia_bot/adapters/hikcentral/selectores.py`.
- **Exploración (Fase 1):** las herramientas están en `exploracion/`. No son código de producción.
- **Guía para trabajar con Claude Code:** [`CLAUDE.md`](CLAUDE.md).
