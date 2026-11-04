# ADR-0007 — Lanzar el bot con `python -m asistencia_bot` (Control inteligente de aplicaciones)

- **Estado:** Aceptada (2026-11-04)
- **Contexto de la decisión:** Fase 4. El reporte del lunes 2026-11-02 no se envió.

## Contexto

Windows 11 tiene activado el **Control inteligente de aplicaciones** (Smart App Control; directiva `VerifiedAndReputableDesktop`, estado 1 = activado). Solo deja ejecutar programas firmados por un fabricante conocido o que Microsoft considera "de buena reputación". La decisión se toma consultando la nube, así que puede cambiar de un día para otro.

Lo que muestra el registro `Microsoft-Windows-CodeIntegrity/Operational`:

| Fecha | Qué bloqueó | Efecto |
|---|---|---|
| Antes del 2026-10-29 | Nada | El ensayo (24/10) y la primera producción (26/10) corrieron bien |
| 2026-10-29 10:00 | `python313.dll`, cargada por `pythonw.exe` | No corrió la vigilancia del lector de ese día |
| 2026-11-02 05:00 y 05:15 | `.venv\Scripts\asistencia-bot.exe` | No se envió el reporte semanal. Nadie recibió aviso, porque el que avisa es el propio bot |

`asistencia-bot.exe` es el lanzador que genera `uv` al instalar el proyecto. No tiene firma y su contenido es único de este equipo, porque incluye la ruta del proyecto, así que nunca tendrá reputación. `python.exe` y `pythonw.exe` (python-build-standalone) tampoco están firmados, pero los usa mucha gente: el 2026-11-04 se ejecutaron sin bloqueo.

Hubo un segundo problema el mismo día. Tras el login, HikCentral mostraba un aviso de que la contraseña de `admin` caducaba en 6 días, y ese aviso tapaba la página. El extractor ahora lo cierra con "Ignorar", que no cambia nada en HikCentral, y lo registra en el log.

## Decisión

- La tarea semanal (`scripts/ejecutar_tarea.ps1`) lanza el bot con `.venv\Scripts\python.exe -m asistencia_bot ejecutar`. La vigilancia ya usaba `pythonw.exe -m asistencia_bot`.
- La documentación y los lanzadores usan `python.exe -m asistencia_bot <comando>` en lugar de `asistencia-bot.exe`.
- Con este cambio, el reporte de la semana del 26/10 al 1/11 se envió el 2026-11-04: código 0, 5 grupos.

## Alternativas

| Alternativa | Estado |
|---|---|
| **Desactivar el Control inteligente de aplicaciones** | Es la única solución confiable. **La decide el cliente o el usuario:** es configuración de seguridad de Windows, y una vez desactivado no se puede volver a activar sin reinstalar el sistema. El antivirus sigue funcionando |
| Firmar los ejecutables | Requiere un certificado de firma de código de una autoridad reconocida (costo anual) y volver a firmar en cada actualización. Además, Python y sus DLL seguirían sin firma |
| Seguir con `asistencia-bot.exe` | Bloqueado: descartado |

## Consecuencias

- **El riesgo no desaparece mientras el control siga activado.** Windows ya bloqueó Python una vez (29/10) y puede volver a hacerlo cualquier día.
- **Cuando Windows bloquea Python, el bot no puede avisar.** Solo queda la línea en `logs\tarea.log` y el resultado de la tarea (`LastTaskResult` 2). El administrador debe esperar el resumen cada lunes hacia las 05:05 y, si no llega, revisar (runbook §10).
- `uv run` sigue funcionando para desarrollo, pero regenera `asistencia-bot.exe`. Eso no afecta a las tareas, porque ya no lo usan.
