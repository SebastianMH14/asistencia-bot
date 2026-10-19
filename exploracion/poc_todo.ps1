# Corre las tres pruebas de la PoC de la Fase 1, una tras otra.
# Lo ejecuta el USUARIO: la PoC escribe la contrasena real (tomada de keyring) en HikCentral.
# Solo imprime pasos, conteos y nombres de archivo.
#
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File exploracion\poc_todo.ps1

Set-Location (Split-Path $PSScriptRoot -Parent)
$py = '.\.venv\Scripts\python.exe'

& .\.venv\Scripts\asistencia-bot.exe credenciales comprobar hikcentral -u admin
if ($LASTEXITCODE -ne 0) { exit 2 }

$pruebas = @(
    @{ nombre = '1/3 visible, ultima semana'; args = @() },
    @{ nombre = '2/3 headless, ultima semana'; args = @('--headless') },
    @{ nombre = '3/3 headless, mes anterior (mas de 100 filas)'; args = @('--headless', '--periodo', 'Mes anterior') }
)

foreach ($p in $pruebas) {
    Write-Host ''
    Write-Host "===== Prueba $($p.nombre) ====="
    & $py exploracion\poc_exportar.py @($p.args)
    $codigo = $LASTEXITCODE
    Write-Host "===== Fin prueba $($p.nombre): codigo $codigo ====="
    if ($codigo -eq 2) {
        Write-Host 'Error en esta prueba; no se corren las siguientes.'
        exit 2
    }
}
Write-Host ''
Write-Host 'Listo. Avisale a Claude para que revise el resultado.'
