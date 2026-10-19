# Diagnóstico del entorno visto desde la terminal real del usuario (fuera de la app de Claude).
# Solo lectura: no instala ni cambia nada.
"APPDATA=$env:APPDATA"
"LOCALAPPDATA=$env:LOCALAPPDATA"
foreach ($c in 'uv', 'git', 'python') {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { "$c -> $($cmd.Source)" } else { "$c -> no encontrado en PATH" }
}
$rutas = @(
    "$env:APPDATA\uv\python",
    "$env:APPDATA\uv\python\cpython-3.13.16-windows-x86_64-none\python.exe",
    "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe",
    "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe",
    "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\uv\python",
    "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\Microsoft\WinGet\Packages"
)
foreach ($r in $rutas) { "{0,-5} {1}" -f (Test-Path $r), $r }
"PATH de usuario contiene WinGet: $([Environment]::GetEnvironmentVariable('Path', 'User') -match 'WinGet')"
