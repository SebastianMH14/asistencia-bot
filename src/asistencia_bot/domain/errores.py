"""Errores del bot.

Los mensajes son técnicos y nunca deben contener datos personales (nombres, cédulas,
horarios) ni secretos: llegan a los logs y al resumen del administrador.
"""


class ErrorBot(Exception):
    """Base de todos los errores propios del bot."""


class ErrorFatal(ErrorBot):
    """Impide continuar con la ejecución completa (código de salida 2)."""


class ErrorConfiguracion(ErrorFatal):
    """Configuración ausente o inválida."""


class ErrorCredenciales(ErrorFatal):
    """No hay contraseña guardada o no es válida."""


class ErrorLogin(ErrorFatal):
    """HikCentral rechazó el inicio de sesión. No se reintenta para no bloquear la cuenta."""


class ErrorEntorno(ErrorFatal):
    """HikCentral, HCWebControl o la carpeta de descargas no están disponibles."""


class ErrorEjecucionEnCurso(ErrorFatal):
    """Otra ejecución del bot tiene el candado."""


class ErrorGrupo(ErrorBot):
    """Falla un grupo; los demás continúan. Se reintenta según la política configurada."""


class ErrorNoReintentable(ErrorGrupo):
    """Falla un grupo por una causa determinista: reintentar no la arregla."""


class ErrorPeriodoNoCoincide(ErrorNoReintentable):
    """HikCentral consultó un rango distinto del periodo esperado."""


class ErrorExtraccion(ErrorGrupo):
    """Falló la interacción con la interfaz de HikCentral."""


class ErrorCaptura(ErrorGrupo):
    """El archivo exportado no apareció o no quedó estable a tiempo."""


class ErrorLectura(ErrorGrupo):
    """No se pudo leer el Excel exportado."""


class ErrorNotificacion(ErrorGrupo):
    """No se pudo enviar un correo tras los reintentos."""


class ErrorArchivo(ErrorGrupo):
    """No se pudo copiar el archivo al histórico o la copia no es idéntica."""
