# ADR-0001 — Ubicación del proyecto y Python fuera de `AppData`

- **Estado:** Aceptada (2026-10-19)
- **Contexto de la decisión:** Fase 0 y preparación de la Fase 1

## Contexto

1. El encargo se abrió en `C:\Program Files\asistencia-bot`. Las terminales no corren elevadas. `BUILTIN\Usuarios` solo tiene lectura en esa carpeta, y el bot necesita escribir `salida/`, `logs/`, `estado.db` y el candado.
2. El equipo no tenía Python, uv ni git. El usuario aprobó instalar uv y git con winget, y Python 3.13 con uv.
3. La app de Claude es un paquete MSIX y virtualiza `AppData` para los procesos que lanza. La primera instalación de Python (`uv python install 3.13`, destino por defecto `%APPDATA%\uv\python`) quedó en `C:\Users\<usuario>\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\uv\python`.
   - La terminal real del usuario no la veía: `did not find executable at ...\AppData\Roaming\uv\python\...`.
   - El Programador de tareas tampoco la vería.
   - Además, la unión `cpython-3.13-windows-x86_64-none` que crea uv no se podía atravesar desde el shell de Claude.

## Decisión

- El proyecto vive en **`C:\Users\<usuario>\asistencia-bot`**: `<usuario>` puede escribir ahí y está fuera de OneDrive.
- Python 3.13 se instala con uv **fuera de `AppData`**, en **`C:\Users\<usuario>\.uv\python`**:
  `uv python install 3.13 --install-dir C:\Users\<usuario>\.uv\python`.
- El entorno virtual se crea con la **ruta concreta** del intérprete, para no depender de uniones:
  `uv venv --clear --python C:\Users\<usuario>\.uv\python\cpython-3.13.16-windows-x86_64-none\python.exe`.
- Se quitó la instalación virtualizada (`uv python uninstall 3.13`). También se reparó el acceso `C:\Users\<usuario>\.local\bin\python3.13.exe`, que había creado la primera instalación.

## Consecuencias

- La terminal del usuario, el shell de Claude y el Programador de tareas ven el mismo Python y el mismo `.venv`.
- La tarea programada puede invocar `C:\Users\<usuario>\asistencia-bot\.venv\Scripts\asistencia-bot.exe` sin depender del PATH ni de uv.
- Para actualizar Python (p. ej. a 3.13.17) hay que repetir los dos comandos con la ruta nueva y luego `uv sync --frozen`. Queda en el runbook.
- Si se instala en otro equipo sin la app de Claude, el destino por defecto de uv funciona; esta decisión solo hace falta por la virtualización MSIX. Se documentará en el README.
