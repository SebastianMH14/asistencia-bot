# ADR-0005 — Validación de filas frente a la paginación rota de HikCentral

- **Estado:** Aceptada (2026-10-20)
- **Contexto de la decisión:** Fase 1. Prueba de más de 100 filas (Fisioterapeutas, "Mes actual") e investigación de la diferencia 205/201.

## Contexto

El encargo pide verificar que la exportación traiga **todas** las filas y no solo la página visible. Para eso se comparaba el Excel con la suma de las páginas de la consulta de la interfaz (`POST /ISAPI/Bumblebee/AttendancePlugin/V1/Record`), porque ni la interfaz ni la API informan el total (`RecordAllCount=-1`).

Hallazgos del 2026-10-20 en la sesión de exploración. Todo se hizo sin imprimir datos personales: los identificadores se cruzaron solo en memoria.

| Prueba | Página 1 | Página 2 | `NextPage` en la página 2 | Suma | Excel |
|---|---|---|---|---|---|
| Última semana, páginas de 100 | 65 | — | — | 65 | **65** |
| Última semana, páginas de 50 | 50 | 15 | 0 | 65 | **65** |
| Mes actual, páginas de 100 | 100 | **101** | **0** | 201 | **205** |
| Mes actual, páginas de 50 | 50 | **51** | **0** | 101 | **205** |
| Mes actual, páginas de 20 | 20 | **21** | **0** | 41 | **205** |

- Cuando hay **más de dos páginas**, la página 2 trae un registro de más y responde `NextPage=0`. La interfaz no permite pasar de la página 2, así que **los registros siguientes son inalcanzables en pantalla**.
- El Excel de "Mes actual" tiene 205 filas, todas con combinación (ID, Fecha) distinta. Se cruzó con `PersonInfo.EmployeeID` = columna "ID" del Excel:
  - 21 de 22 personas coinciden exactamente.
  - A una persona le faltaban 4 días en la consulta paginada que **sí** están en el Excel.
  - No hay ningún registro de la consulta que falte en el Excel.
- **Conclusión:** la exportación "Predefinido" se genera completa en el servidor. La que pierde registros es la paginación de la interfaz y de su API.

## Decisión

El extractor recorre las páginas de la consulta y guarda, **solo en memoria**, las claves `(EmployeeID, Date)` de los registros vistos. El validador lee del Excel, también en memoria, las claves `(ID, Fecha)`. Las reglas son:

1. **Consulta de una sola página** (`NextPage=0` en la página 1): las filas del Excel deben ser **exactamente iguales** a los registros de la consulta. Si difieren, el grupo **falla**.
2. **Consulta de varias páginas:**
   - **Toda clave vista en la consulta debe estar en el Excel.** Si falta alguna, el Excel está truncado (por ejemplo, solo la página visible) y el grupo **falla**.
   - Las filas del Excel deben ser **≥** la suma de las páginas.
   - La diferencia se informa en el resumen al administrador como dato, porque es esperable por el defecto de paginación, y no bloquea el envío.
3. **Sin registros** (consulta vacía y Excel sin filas): se aplica la política "sin registros".
4. Las claves nunca se registran, persisten ni envían. En logs y resúmenes solo van conteos.

## Consecuencias

- Se cubre el riesgo que pedía el encargo, un Excel con solo la página visible, sin depender de un total que HikCentral no da bien.
- El dominio maneja identificadores de empleado en memoria durante la validación. Las reglas de la sección 13 de la arquitectura (no registrar ni persistir datos personales) se mantienen y se cubren con pruebas.
- Si una semana de un grupo supera 100 registros, se aplica la regla 2. Con los volúmenes observados (Fisioterapeutas, 22 personas: 65 registros por semana) lo normal es la regla 1.
- Si Hikvision corrige la paginación en una versión futura, la regla sigue siendo válida.
