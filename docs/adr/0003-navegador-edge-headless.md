# ADR-0003 — Navegador: Edge instalado, headless

- **Estado:** Aceptada (2026-10-20)
- **Contexto de la decisión:** Fase 1, PoC `exploracion/poc_exportar.py`, corridas del 2026-10-20 a las 05:30

## Contexto

- En el equipo están Edge 155 y Chrome 155. Playwright 1.64 puede usarlos con `channel=` sin descargar su propio Chromium; descargar navegadores requiere permiso.
- La exportación la hace HCWebControl, no el navegador (ADR-0002). Al navegador solo le toca hablar con la web de HikCentral y, por WebSocket en `127.0.0.1:15000`, con HCWebControl.

Resultado de la PoC con `channel="msedge"`, Fisioterapeutas y Última semana:

| Modo | Login | Exportación y captura | Validación (periodo, departamento, 65/65 filas) | Cierre de sesión | Duración total |
|---|---|---|---|---|---|
| Visible | OK | Archivo estable 4,1 s después del clic | OK | OK | 33,5 s |
| **Headless** | OK | Archivo estable 3,6 s después del clic | OK | OK | 26,3 s |

## Decisión

- Producción usa **Edge instalado (`channel="msedge"`) en modo headless**, con viewport 1600×900 y `locale="es-ES"`.
- `--visible` queda para depurar.
- Chrome (`channel="chrome"`) es la alternativa configurable. No se probó porque no hizo falta.
- **No** se descargan los navegadores de Playwright.

## Consecuencias

- Las actualizaciones automáticas de Edge podrían romper la compatibilidad con Playwright. Hay que mantener Playwright al día (`uv lock --upgrade-package playwright`) y `verificar` debe detectar si falla el arranque del navegador.
- Headless **no elimina** la dependencia de HCWebControl, que solo corre si `<usuario>` inició sesión en Windows. Desde cualquier sesión del equipo se le habla por `127.0.0.1`.
  - La opción de la tarea programada ("solo con sesión iniciada" o "tanto si inició sesión como si no") se decide en la Fase 4.
  - En ambos casos debe haber una sesión de `<usuario>` abierta para que HCWebControl esté vivo.
