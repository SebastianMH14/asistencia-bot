# Runbook — operación de asistencia-bot

Para quien opera el bot en el equipo de HikCentral. Los comandos se ejecutan en PowerShell desde `C:\Users\<usuario>\asistencia-bot`, con el usuario de Windows `<usuario>`:

```powershell
.venv\Scripts\asistencia-bot.exe <comando>
```

## 1. Operación normal

- **Cada lunes** (hora configurada en la tarea programada) el bot envía a cada jefe el Excel de la semana anterior.
- El administrador recibe un correo de resumen: `[asistencia-bot] OK – semana del …`.
- Para ver qué pasó:
  - `asistencia-bot estado` muestra las últimas ejecuciones y el estado de cada grupo.
  - `logs\bot.jsonl` es el log detallado, en JSON y sin datos personales.
- **Requisito:** el usuario `<usuario>` debe tener la sesión de Windows iniciada. HCWebControl, que es el que guarda los Excel, solo corre en esa sesión.

## 2. Qué hacer según el resultado

| Código / asunto | Significado | Qué hacer |
|---|---|---|
| `0` · "OK" | Todo enviado, o grupos omitidos a propósito (ya enviados o sin registros) | Nada |
| `1` · "con fallos" | Al menos un grupo falló, o no se pudo enviar el resumen | Leer la columna *Detalle* del resumen (y las capturas adjuntas). Corregir y **reenviar solo ese grupo** (sección 4) |
| `2` · "ERROR" | Error fatal: no se procesó ningún grupo, o se cortó a mitad | Ver la sección 3. Luego ejecutar de nuevo. Los grupos ya enviados no se repiten |

## 3. Errores frecuentes

| Mensaje | Causa probable | Solución |
|---|---|---|
| `HCWebControl no escucha en 127.0.0.1:15000` | Nadie inició sesión en Windows tras un reinicio | Iniciar sesión con `<usuario>`, esperar un minuto y volver a ejecutar |
| `HikCentral no responde en https://127.0.0.1/` | Servicios de HikCentral detenidos | Revisar los servicios (SYS, Nginx, PostgreSQL) o reiniciar el equipo |
| `HikCentral no completó el inicio de sesión` | Cambió la contraseña de HikCentral | `credenciales configurar hikcentral -u admin` |
| `no hay contraseña de HikCentral/SMTP` | No se configuró o se borró | `credenciales configurar …` (sección 6) |
| `el servidor SMTP rechazó usuario o contraseña` | Contraseña SMTP vencida o cambiada (en Gmail: contraseña de aplicación revocada) | `credenciales configurar smtp -u <usuario>` |
| `no apareció '…xlsx' estable en 120 s` | Alguien cambió la "Ubicación de descarga personalizada" en el Centro de descargas, o HCWebControl está colgado | Dejarla en `C:\Users\<usuario>\HCWebControlService\Downloadcenter` (o ajustar `hikcentral.carpeta_descargas`); cerrar sesión y volver a entrar en Windows |
| `HikCentral consultó … y se esperaba …` | El bot corrió en una semana distinta de la esperada | Normal si se ejecuta muy tarde; el periodo se calcula con la fecha de ejecución |
| `el periodo del Excel … no es el esperado` | El Excel no es de la semana anterior | Revisar el filtro en HikCentral; reintentar |
| `el Excel trae departamentos que no son de …` | Se seleccionó mal el grupo, o cambió el árbol de departamentos | Revisar `departamento_hik` en `config\grupos.yaml` (nombre exacto; "Medicos" va sin tilde) |
| `… registros vistos en la consulta no están en el Excel` | Exportación truncada | Reintentar ese grupo; si persiste, avisar al soporte |
| Advertencia `diferencia esperable por la paginación de HikCentral` | Defecto conocido de HikCentral con más de 100 registros ([ADR-0005](adr/0005-validacion-de-filas.md)) | Ninguna: el Excel está completo |
| `ya hay una ejecución en curso` | Otra ejecución está corriendo | Esperar a que termine |
| `no se procesó` en todos los grupos | Hubo un error fatal antes (ver el encabezado del resumen) | Resolver el error fatal |

**Evidencias:** cuando un grupo falla, el resumen adjunta una captura (`capturas\`) y, si existe, un *trace* de Playwright (`traces\`).
- Pueden mostrar datos personales: **no reenviarlas**.
- El trace se abre con `uv run playwright show-trace traces\<archivo>.zip`.

## 4. Reenviar

- **Un grupo de la semana anterior**, aunque ya se haya enviado:

  ```powershell
  asistencia-bot ejecutar --modo produccion --grupo "Fisioterapeutas" --forzar
  ```

- **Probar antes sin molestar a los jefes:** usar `--modo prueba` (llega solo al administrador) o `--dry-run` (no envía nada).
- **Semanas anteriores o rangos arbitrarios:** no está incluido en el alcance actual. HikCentral sí permite un rango "Personalizado"; queda como mejora futura.

## 5. Cambiar destinatarios o grupos

1. Editar `config\grupos.yaml` (ver [guía del cliente](guia-cliente.md)).
2. Comprobar:

   ```powershell
   asistencia-bot verificar
   asistencia-bot ejecutar --dry-run --grupo "<grupo>"
   ```

## 6. Contraseñas

```powershell
asistencia-bot credenciales configurar hikcentral -u admin           # la pide sin mostrarla
asistencia-bot credenciales configurar smtp -u reportes@ejemplo.com
asistencia-bot credenciales comprobar hikcentral -u admin            # solo dice si existe
asistencia-bot credenciales borrar smtp -u reportes@ejemplo.com
```

Hay que hacerlo con el **mismo usuario de Windows** que ejecuta la tarea programada. Las contraseñas quedan en el Administrador de credenciales de Windows, en las entradas `asistencia-bot/hikcentral` y `asistencia-bot/smtp`.

## 7. Activar producción (solo con aprobación del cliente)

En `config\settings.toml`:

```toml
[ejecucion]
produccion_habilitada = true
modo_por_defecto = "produccion"
```

Luego ejecutar `asistencia-bot verificar`. Exige que todos los grupos activos tengan jefe.

## 8. Logs, histórico y retención

- `logs\bot.jsonl`: una línea JSON por evento, con rotación de 5 MB × 10 archivos. Sin nombres, cédulas ni contraseñas.
- `salida\<semana>\`: copia exacta de cada Excel enviado.
- `estado.db`: historial (`asistencia-bot estado`).
- La retención es configurable en `[retencion]`: Excel 180 días; logs, capturas y traces 90 días. Se aplica al final de cada ejecución y **solo** a archivos del bot. Nunca toca `Downloadcenter`.

## 9. Actualizar el bot

```powershell
git pull
uv sync --frozen
asistencia-bot verificar
```

Si Edge se actualiza y Playwright deja de controlarlo: `uv lock --upgrade-package playwright`, luego `uv sync`, y probar con `ejecutar --dry-run`.

## 10. Tarea programada

Pendiente de la Fase 4 (`scripts\registrar_tarea.ps1`).
