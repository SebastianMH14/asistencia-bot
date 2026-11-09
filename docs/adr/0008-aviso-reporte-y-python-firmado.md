# ADR-0008 — Aviso si el reporte semanal no sale, y Python firmado

- **Estado:** Aceptada (2026-11-08).
  - El aviso funciona desde el 2026-11-08.
  - El cambio a Python firmado se hace el 2026-11-09, después del envío de las 05:00 y con una prueba en seco.
- **Contexto de la decisión:** Fase 4. Continúa el [ADR-0007](0007-lanzar-con-python-m.md).

## Contexto

El lunes 2026-11-02 el reporte no salió y nadie se enteró hasta el miércoles. El Control inteligente de aplicaciones de Windows bloqueó el lanzador, y quien avisa de los fallos es el propio bot.

El usuario decidió **mantener activado** el Control inteligente de aplicaciones. Desactivarlo es irreversible. Con el control activo quedan dos riesgos.

**1. Los binarios de Python no tienen firma.** Revisión del 2026-11-08:

| Binario | Firma |
|---|---|
| `python.exe`, `pythonw.exe` y `python313.dll` de python-build-standalone (lo que instala `uv`) | Ninguno firmado |
| Módulos nativos de la biblioteca estándar de ese mismo Python | 36 de 39 sin firma |
| Módulos nativos de terceros que carga el bot (`pydantic_core`, PyYAML, MarkupSafe, greenlet) | Sin firma, pero son binarios de PyPI que usa muchísima gente y nunca se han bloqueado |
| `node.exe` de Playwright | Firmado (OpenJS Foundation) |

Lo que no está firmado depende de la reputación que le dé la nube de Microsoft. Por eso hubo un bloqueo el 29/10 (`python313.dll`) y otro el día siguiente no.

**2. Un fallo silencioso tarda en notarse.** Si el bot no llega a arrancar, el administrador solo lo nota si se da cuenta de que el resumen del lunes no llegó.

**Riesgo descartado: que el equipo se reinicie y nadie inicie sesión.** La sesión de Windows se abre sola al arrancar. Así pasó en los 10 reinicios desde septiembre, incluidos dos de madrugada por Windows Update. Sigue el caso de un corte de luz si el equipo no vuelve a encenderse solo, lo que depende del BIOS.

## Decisión

1. **Aviso si el reporte no salió.** `vigilar-lector` (lunes a sábado, 10:00) también revisa `estado.db`.
   - Desde el lunes a las `[vigilancia] plazo_reporte` (09:00 por defecto), si no hay ninguna ejecución de producción **terminada** de la semana anterior, le manda al administrador `[asistencia-bot] ALERTA – el reporte semanal no salió (semana dd/mm al dd/mm)`. El correo explica qué hacer.
   - El aviso se repite cada día mientras falte.
   - Una ejecución con fallos cuenta como hecha, porque ya mandó su resumen. Lo que se busca es el silencio.
   - Solo se revisa con `modo_por_defecto = "produccion"`.
   - Si no se puede leer el historial, la vigilancia lo registra, sale con código 1 y sigue revisando el lector.
2. **Python oficial firmado.**
   - El `.venv` se reconstruye sobre el Python oficial de python.org, cuyos `python.exe`, `pythonw.exe`, `python313.dll` y biblioteca estándar firma la Python Software Foundation.
   - El Control inteligente de aplicaciones deja pasar los programas firmados sin consultar la nube.
   - Las tareas no cambian: siguen lanzando `.venv\Scripts\python.exe -m asistencia_bot` y `pythonw.exe`.

## Alternativas

| Alternativa | Estado |
|---|---|
| Desactivar el Control inteligente de aplicaciones | El usuario prefirió mantenerlo, porque es irreversible |
| Que el script de PowerShell de la tarea avise si Python no arranca | Necesita la contraseña SMTP fuera de keyring, o compilar código (`Add-Type`) que ese mismo control puede bloquear |
| Firmar con un certificado propio | Tiene un costo anual y hay que volver a firmar en cada actualización (ADR-0007) |

## Consecuencias

- **El fallo silencioso se detecta el mismo lunes a las 10:00**, siempre que el equipo esté encendido y Python arranque a esa hora. Con Python firmado, que Windows lo bloquee a las 05:00 y otra vez a las 10:00 es improbable.
- **El aviso no cubre el equipo apagado,** porque entonces no corre nada. Al encenderlo, las dos tareas corren en cuanto pueden.
  - Si se enciende el lunes después de las 10:00, el aviso puede llegar mientras el reporte está saliendo.
  - El correo lo advierte: hay que esperar unos 20 minutos el resumen antes de hacer nada.
- Con Python firmado solo quedan sin firma los cuatro módulos de terceros. Si alguno se bloquea, aparece en `Microsoft-Windows-CodeIntegrity/Operational` (eventos 3077 y 3033) y el aviso de las 10:00 lo hace visible.
