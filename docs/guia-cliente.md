# Guía rápida: grupos y destinatarios

Los grupos que reciben el reporte de asistencia de cada lunes se definen en un solo archivo:

```
C:\Users\<usuario>\asistencia-bot\config\grupos.yaml
```

Ábralo con el Bloc de notas. Cada grupo se ve así:

```yaml
  - nombre: Fisioterapeutas            # aparece en el asunto y en el nombre del archivo
    departamento_hik: Fisioterapeutas  # nombre EXACTO del departamento en HikCentral
    activo: true                       # false = no se envía, sin borrar el grupo
    jefe: { nombre: "Nombre del jefe", correo: "jefe@ejemplo.com" }
    cc: ["coordinacion@ejemplo.com"]     # copias; [] si no hay
```

## Cambiar el jefe o las copias
Cambie `correo:` dentro de `jefe:`, o la lista `cc:`. Se pueden poner varias copias, separadas por comas y entre comillas: `cc: ["a@ejemplo.com", "b@ejemplo.com"]`.

## Agregar un grupo
Copie un bloque completo (desde el guion `-`) al final y cambie los valores.
- `departamento_hik` debe escribirse **igual** que en HikCentral (Persona → departamentos bajo *General*).
- Ojo con las tildes: en HikCentral, "Medicos" está **sin** tilde.

## Pausar un grupo
Cambie `activo: true` por `activo: false`.

## Reglas para que el archivo sea válido
- Respete los espacios del principio de cada línea: dos espacios antes del guion y cuatro antes de cada campo. No use tabuladores.
- Los nombres de grupo no se pueden repetir.
- Debe haber al menos un grupo activo.

## Comprobar el cambio
En PowerShell, desde `C:\Users\<usuario>\asistencia-bot`:

```powershell
.venv\Scripts\asistencia-bot.exe verificar
```

Todo debe decir **OK**. Si sale **FALLA**, el mensaje indica qué línea o campo corregir.

¿Dudas o algo no funciona? Escriba al administrador del bot con el texto exacto del error.
