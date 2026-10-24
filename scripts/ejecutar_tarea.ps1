<#
.SYNOPSIS
    Lo que lanza la tarea programada: espera a que el entorno esté listo, ejecuta el bot y,
    ante un error fatal (código 2), lo reintenta una vez.

.DESCRIPTION
    Si el equipo se reinició, la tarea arranca en cuanto el usuario inicia sesión ("lo antes
    posible si se omitió"), a veces antes de que HCWebControl y HikCentral estén arriba. Por eso
    primero espera a que respondan; si no responden, ejecuta igual para que el bot avise al
    administrador.

    La salida de cada intento queda en logs\tarea\ y una línea por evento en logs\tarea.log.
    La salida del bot solo trae grupos, conteos, estados y destinatarios: nada de nombres,
    cédulas ni horarios.

.PARAMETER CorreoEnsayo
    Ensayo: fuerza el modo prueba y manda todos los correos a este destinatario en lugar del
    administrador, solo en esta ejecución.

.PARAMETER Exe
    Ejecutable del bot. Solo se cambia para probar este script.
#>
[CmdletBinding()]
param(
    [string]$CorreoEnsayo,
    [int]$EsperaMaxMin = 15,
    [int]$PausaReintentoMin = 15,
    [string]$Exe
)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
if (-not $Exe) { $Exe = Join-Path $raiz '.venv\Scripts\asistencia-bot.exe' }
$carpetaTarea = Join-Path $raiz 'logs\tarea'
$registro = Join-Path $raiz 'logs\tarea.log'
New-Item -ItemType Directory -Force -Path $carpetaTarea | Out-Null
Set-Location $raiz

function Anotar([string]$texto) {
    Add-Content -Path $registro -Encoding UTF8 -Value ('{0:yyyy-MM-dd HH:mm:ss}  {1}' -f (Get-Date), $texto)
}

function Test-Puerto([int]$puerto) {
    $cliente = New-Object System.Net.Sockets.TcpClient
    try {
        $conexion = $cliente.BeginConnect('127.0.0.1', $puerto, $null, $null)
        return ($conexion.AsyncWaitHandle.WaitOne(3000) -and $cliente.Connected)
    } catch {
        return $false
    } finally {
        $cliente.Close()
    }
}

# HikCentral (nginx) y HCWebControl, el servicio que escribe los Excel.
$limite = (Get-Date).AddMinutes($EsperaMaxMin)
while (-not ((Test-Puerto 443) -and (Test-Puerto 15000))) {
    if ((Get-Date) -ge $limite) {
        Anotar "HikCentral o HCWebControl no respondieron en $EsperaMaxMin min; se ejecuta igual para que el bot avise"
        break
    }
    Start-Sleep -Seconds 15
}

$argumentos = @('ejecutar')
if ($CorreoEnsayo) {
    $argumentos += @('--modo', 'prueba')
    $env:ASISTENCIA_BOT_ADMINISTRADOR__CORREO = $CorreoEnsayo
}
$env:PYTHONIOENCODING = 'utf-8'

$codigo = $null
foreach ($intento in 1..2) {
    $marca = Get-Date -Format 'yyyy-MM-dd_HHmmss'
    $salida = Join-Path $carpetaTarea "$marca.txt"
    $errores = Join-Path $carpetaTarea "$marca.err.txt"
    Anotar "intento ${intento}: asistencia-bot $($argumentos -join ' ')$(if ($CorreoEnsayo) { ' (ensayo)' })"
    try {
        $proceso = Start-Process -FilePath $Exe -ArgumentList $argumentos -WorkingDirectory $raiz `
            -NoNewWindow -Wait -PassThru -RedirectStandardOutput $salida -RedirectStandardError $errores
        $codigo = $proceso.ExitCode
    } catch {
        Anotar "no se pudo lanzar el bot: $($_.Exception.Message)"
        $codigo = 2
    }
    if ((Test-Path $errores) -and (Get-Item $errores).Length -eq 0) { Remove-Item $errores }
    Anotar "intento $intento terminó con código $codigo (salida en logs\tarea\$marca.txt)"
    # 0 y 1 ya los reporta el bot; 1 se corrige a mano y el reenvío no repite lo enviado.
    if ($codigo -ne 2 -or $intento -eq 2) { break }
    Start-Sleep -Seconds ($PausaReintentoMin * 60)
}

# Retención de las salidas de este script (las del bot las limpia el propio bot).
Get-ChildItem -Path $carpetaTarea -File |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-90) } |
    Remove-Item

exit $codigo
