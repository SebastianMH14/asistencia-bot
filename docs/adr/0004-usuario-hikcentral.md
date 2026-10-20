# ADR-0004 — Usuario de HikCentral para el bot

- **Estado:** Propuesta. Pendiente de decisión del cliente.
- **Contexto de la decisión:** Fase 1, prueba de sesión del 2026-10-19

## Contexto

Regla 7 del encargo: el usuario `admin` puede tener una sesión abierta por una persona, y había que verificar si el login del bot la cierra.

Prueba realizada:
1. Una sesión de `admin` abierta en el Edge de exploración.
2. La PoC inició otra sesión de `admin` en un navegador nuevo (19/10, 17:30).
3. Después, la sesión del Edge siguió válida en el servidor: la consulta `POST /ISAPI/Bumblebee/AttendancePlugin/V1/Record` respondió `ErrorCode=0` con datos.

Las corridas del 20/10 iniciaron y cerraron sesión 3 veces sin afectar a nadie.

**Conclusión:** HikCentral AC 2.4 admite sesiones simultáneas del mismo usuario. El login del bot **no** cierra la sesión de una persona.

Otros hechos relevantes:
- El Excel exportado incluye la línea `Operador: <usuario>`. Con un usuario dedicado, los jefes verían, por ejemplo, `Operador: bot-asistencia` en vez de `admin`.
- La sesión expira por inactividad. La interfaz muestra la notificación *"Inicie sesión de nuevo."* (`.el-notification.session-expire-notification`), que bloquea los clics. El bot debe detectarla y volver a iniciar sesión una vez.

## Opciones

| Opción | A favor | En contra |
|---|---|---|
| A. Seguir con `admin` | Ya funciona; no requiere cambios en HikCentral | El bot tiene todos los permisos. Si alguien cambia la contraseña de `admin`, el bot falla hasta actualizar `keyring`. La auditoría no distingue al bot de las personas. |
| B. **Usuario dedicado** (p. ej. `bot-asistencia`) con permiso solo para consultar y exportar asistencia | Mínimo privilegio, auditoría separada y contraseña independiente de la de las personas | Crearlo es un cambio de configuración en HikCentral: requiere aprobación y lo hace el cliente o se hace con su visto bueno. Hay que repetir `credenciales configurar`. |

## Recomendación

**Opción B**, por mínimo privilegio y trazabilidad. Ya no hace falta para evitar sesiones cerradas, porque eso se descartó. Hasta que el cliente decida, se usa `admin`. El usuario es configurable (`hikcentral.usuario`).
