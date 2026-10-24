<#
.SYNOPSIS
    Registra en el Programador de tareas la ejecución semanal del bot y, si se pide, un ensayo.

.DESCRIPTION
    Debe ejecutarlo el MISMO usuario de Windows que guardó las contraseñas en el Administrador
    de credenciales, desde su propia terminal y no desde el shell de la app de Claude
    (ADR-0001). No necesita permisos de administrador ni la contraseña de Windows: la tarea
    corre solo con la sesión de ese usuario iniciada, porque HCWebControl solo vive en esa
    sesión (arquitectura, R2).

    La tarea lanza scripts\ejecutar_tarea.ps1, que espera al entorno, ejecuta
    `asistencia-bot ejecutar` (modo según `modo_por_defecto`) y reintenta una vez ante un
    error fatal. Volver a ejecutar este script reemplaza las tareas existentes.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\registrar_tarea.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\registrar_tarea.ps1 -Ensayo '2026-10-24 05:00' -CorreoEnsayo yo@ejemplo.com

    Además de la semanal, registra una ejecución única en modo prueba que manda todo a ese
    correo. La tarea del ensayo se borra sola 7 días después.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\registrar_tarea.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')]
    [string]$Dia = 'Monday',
    [ValidatePattern('^\d{2}:\d{2}$')]
    [string]$Hora = '05:00',
    [datetime]$Ensayo,
    [string]$CorreoEnsayo
)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
$lanzador = Join-Path $PSScriptRoot 'ejecutar_tarea.ps1'
$bot = Join-Path $raiz '.venv\Scripts\asistencia-bot.exe'
$nombreSemanal = 'asistencia-bot - reporte semanal'
$nombreEnsayo = 'asistencia-bot - ensayo'

foreach ($ruta in @($lanzador, $bot)) {
    if (-not (Test-Path $ruta)) { throw "No existe $ruta" }
}
if ($PSBoundParameters.ContainsKey('Ensayo') -and -not $CorreoEnsayo) {
    throw 'El ensayo necesita -CorreoEnsayo: es el único destinatario de sus correos.'
}

$usuario = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited

function Nueva-Accion([string]$extra) {
    $argumentos = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$lanzador`"$extra"
    New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argumentos -WorkingDirectory $raiz
}

function Nuevos-Ajustes {
    param([switch]$BorrarAlVencer)
    $opciones = @{
        StartWhenAvailable         = $true   # "lo antes posible si se omitió un inicio programado"
        WakeToRun                  = $true
        AllowStartIfOnBatteries    = $true
        DontStopIfGoingOnBatteries = $true
        ExecutionTimeLimit         = New-TimeSpan -Hours 2
        MultipleInstances          = 'IgnoreNew'
    }
    if ($BorrarAlVencer) { $opciones.DeleteExpiredTaskAfter = New-TimeSpan -Days 7 }
    New-ScheduledTaskSettingsSet @opciones
}

$disparador = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Dia -At $Hora
$semanal = New-ScheduledTask -Action (Nueva-Accion '') -Trigger $disparador -Principal $principal `
    -Settings (Nuevos-Ajustes) `
    -Description "Cada $Dia a las $Hora envía a cada jefe el reporte de asistencia de la semana anterior (asistencia-bot, modo según config\settings.toml)."
if ($PSCmdlet.ShouldProcess($nombreSemanal, "Registrar: $Dia $Hora, usuario $usuario")) {
    Register-ScheduledTask -TaskName $nombreSemanal -InputObject $semanal -Force | Out-Null
}

if ($PSBoundParameters.ContainsKey('Ensayo')) {
    $unaVez = New-ScheduledTaskTrigger -Once -At $Ensayo
    # Sin fin no se puede borrar sola; tres horas bastan para un arranque tardío.
    $unaVez.EndBoundary = $Ensayo.AddHours(3).ToString('s')
    $ensayoTarea = New-ScheduledTask -Action (Nueva-Accion " -CorreoEnsayo `"$CorreoEnsayo`"") `
        -Trigger $unaVez -Principal $principal -Settings (Nuevos-Ajustes -BorrarAlVencer) `
        -Description 'Ensayo único de asistencia-bot en modo prueba: ningún jefe recibe nada.'
    if ($PSCmdlet.ShouldProcess($nombreEnsayo, "Registrar: $($Ensayo.ToString('yyyy-MM-dd HH:mm')), modo prueba")) {
        Register-ScheduledTask -TaskName $nombreEnsayo -InputObject $ensayoTarea -Force | Out-Null
    }
}

if (-not $WhatIfPreference) {
    Get-ScheduledTask | Where-Object { $_.TaskName -like 'asistencia-bot*' } | ForEach-Object {
        $info = $_ | Get-ScheduledTaskInfo
        '{0}: {1}, próxima ejecución {2:yyyy-MM-dd HH:mm}' -f $_.TaskName, $_.State, $info.NextRunTime
    }
}
