# ADR-0002 — Captura del Excel vigilando la carpeta Downloadcenter

- **Estado:** Aceptada (2026-10-19). Pendiente de confirmarse en modo headless con la PoC.
- **Contexto de la decisión:** Fase 1, exportación de prueba de Fisioterapeutas (Última semana)

## Contexto

En HikCentral AC 2.4, el botón *Exportar* no genera una descarga del navegador:
- La página verifica la contraseña (`/ISAPI/Bumblebee/Platform/V0/CheckPassword`).
- La exportación la hace **HCWebControl**, el componente local de `C:\Program Files\HCWebControl` que corre en la sesión de Windows de `<usuario>`.
- HCWebControl escribe el archivo en `C:\Users\<usuario>\HCWebControlService\Downloadcenter\<Reporte>_<AAAA_MM_DD_HH_MM_SS>\<Reporte>_<desde>_<hasta>.xlsx`.

Se probaron las dos estrategias del encargo en la misma exportación:

| Estrategia | Resultado |
|---|---|
| a) `page.on("download")` / `page.expect_download()` | No se disparó ningún evento. Nada en `Descargas`. |
| b) Vigilar la carpeta Downloadcenter | Carpeta nueva al instante. El `.xlsx` apareció a los ~1,5 s y quedó estable ~1,6 s después. |
| c) Repetir con Edge | No aplica: la prueba ya se hizo con Edge. El mecanismo no depende del navegador sino de HCWebControl. |

## Decisión

El adaptador `adapters/descargas.py` **vigila Downloadcenter**:

1. Antes de pulsar *Exportar*, registra los nombres de las subcarpetas existentes.
2. Busca una subcarpeta **nueva** que empiece por `Registros de entradas y salidas_`, con un archivo cuyo nombre sea exactamente `Registros de entradas y salidas_<desde>_<hasta>.xlsx`.
3. Considera el archivo listo cuando su tamaño no cambia en 3 sondeos seguidos (cada 0,5 s).
4. Si no aparece en el tiempo límite configurable (por defecto 120 s), falla con `ErrorCaptura`; el reintento queda a cargo del servicio.
5. **Solo copia.** Nunca mueve, renombra ni borra nada en Downloadcenter.

La ruta de Downloadcenter se configura (`hikcentral.carpeta_descargas`).

## Consecuencias

- **HCWebControl tiene que estar corriendo** en la sesión de `<usuario>`, y el bot tiene que correr en esa misma sesión (ver la tarea programada en la arquitectura, R2). `verificar` comprueba el proceso y la carpeta.
- Si alguien cambia la "Ubicación de descarga personalizada" en el Centro de descargas, el bot dejará de encontrar los archivos y fallará con un error claro, sin enviar nada. El runbook lo documenta.
- El nombre esperado incluye el periodo, así que el bot no confunde una exportación manual simultánea de otra semana. Una exportación manual de **la misma** semana en el mismo segundo es improbable; en ese caso el bot tomaría la carpeta más reciente con el nombre esperado.
- Como el evento de descarga del navegador no participa, en principio da igual qué navegador se use (ADR-0003).
