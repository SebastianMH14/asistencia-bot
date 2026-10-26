# ADR-0006 — Vigilancia diaria del lector a partir del log de HikCentral

- **Estado:** Aceptada (2026-10-26)
- **Contexto de la decisión:** Fase 4. La primera ejecución de producción envió una semana con datos de solo dos días.

## Contexto

El reporte del 2026-10-26 (semana del 19 al 25/10) trajo registros solo del lunes 19 y del martes 20. El bot validó bien: la consulta y el Excel coincidían. El problema estaba antes, en HikCentral. Los logs de HikCentral, leídos solo en lectura y sin datos personales, mostraron lo siguiente:

- El lector dejó de enviarle eventos a HikCentral el **2026-10-20 a las 16:44** y no volvió a enviar hasta el **2026-10-26 a las 08:35**, cuando alguien lo reconectó y reinició el servidor.
- Ya había pasado antes: del **2026-10-08 a las 19:07** al **2026-10-13 a las 23:21**.
- En los dos casos **HikCentral siguió mostrando el lector como conectado**: la falla no avisa por sí sola.
- El cálculo de asistencia corrió todos los días, pero sin eventos no genera registros.

La alerta del resumen semanal ("días sin registros") lo detecta, pero el lunes siguiente: hasta 5 días tarde, y quizá cuando el lector ya descartó los eventos que tenía guardados.

Mientras le llegan eventos de los lectores, HikCentral escribe cada ~30 s una línea en `VSM Servers\Log\SYS\baseacs.d\EventStatistics.log` como esta:

```
[2026-10-20 16:44:08.337][baseacs.d.EventStatistics][INFO][...::TimePrintLog]Last 30 s,  receive 0 succ(avg:0/s),  1 input(avg:0/s)[...]
```

`input` es el número de eventos recibidos. Cuando el canal del lector se cae, deja de escribir esas líneas. El log solo contiene conteos, sin datos personales.

## Decisión

1. Un comando nuevo, `asistencia-bot vigilar-lector`:
   - Suma los `input` del log desde las 00:00 de hoy.
   - Si la suma es 0, o si no puede leer el log, envía una alerta al administrador con la última marcación recibida y qué hacer.
   - Códigos de salida: 0 hay marcaciones, 1 no hay o no se pudo revisar, 2 había que avisar y no se pudo.
   - `--sin-correo` solo muestra el resultado.
2. Una tarea diaria, `asistencia-bot - vigilancia del lector`, que corre de lunes a sábado a las 10:00:
   - Usa `pythonw -m asistencia_bot vigilar-lector`, sin ventanas, porque corre en plena jornada en el equipo de recepción.
   - Se registra con `scripts/registrar_tarea.ps1` (`-HoraVigilancia` para cambiar la hora).
3. Estructura del código:
   - El dominio (`domain/vigilancia.py`) no conoce el formato del log.
   - El adaptador `adapters/log_eventos_hik.py` lo interpreta.
   - La ruta va en `[vigilancia] log_eventos`.

Con el log real, una revisión diaria a las 10:00 no habría dado ninguna falsa alarma entre el 5 y el 26/10 (incluido el sábado 17, con 82 eventos). Habría avisado el **viernes 9/10** y el **miércoles 21/10**, la primera mañana de cada caída.

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Iniciar sesión en HikCentral cada día y consultar los eventos | Otro inicio de sesión diario con la contraseña, más frágil (interfaz, sesión) y más lento. El log da lo mismo sin tocar HikCentral |
| OpenAPI de HikCentral | No está activa (`/artemis` → 502) |
| Comprobar si el lector está conectado (ping o estado en HikCentral) | Las dos caídas fueron con el lector "conectado": no las habría detectado |
| Esperar a la alerta del lunes | Llega hasta 5 días tarde |

## Consecuencias

- **Depende de un log interno de HikCentral.** Una actualización puede cambiar su ruta o su formato. En ese caso no falla en silencio:
  - Si la ruta no existe, avisa "no se pudo revisar el lector".
  - Si cambia el formato, avisa "el log no tiene ninguna marcación".
- **Los festivos dan una falsa alarma**, igual que un día en que la sede no abra. El correo lo dice.
- **Solo detecta la falta total de marcaciones.** Una caída parcial, por ejemplo uno de varios lectores, no se nota mientras otro siga enviando. Hoy hay un único lector.
- Necesita la sesión de Windows iniciada, igual que la tarea semanal. Si el equipo se reinicia y nadie inicia sesión, tampoco avisa.
