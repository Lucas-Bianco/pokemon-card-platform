# Run at Windows logon (Task Scheduler task "Pokemon card app"). Keeps the app up for the phone:
#   backend   uvicorn on 127.0.0.1:8000 (this PC only)
#   front end vite preview on https://127.0.0.1:4173 (serves frontend/dist, proxies /api to the backend)
# `tailscale serve` (set up once, survives reboots) puts 4173 on the tailnet. If either process
# exits it is started again after 15 s. Logs: %LOCALAPPDATA%\PokemonCardPlatform\logs (never the
# shared data store). Builds frontend/dist first if it is missing.
$root = Split-Path -Parent $PSScriptRoot
$front = Join-Path $root "frontend"
$logDir = Join-Path $env:LOCALAPPDATA "PokemonCardPlatform\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null

function Start-Part($name, $file, $argList, $dir) {
    $out = Join-Path $logDir "$name.log"
    $err = Join-Path $logDir "$name.err.log"
    foreach ($f in $out, $err) {
        if ((Test-Path $f) -and (Get-Item $f).Length -gt 2MB) { Remove-Item $f }
    }
    Start-Process -FilePath $file -ArgumentList $argList -WorkingDirectory $dir -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
}

if (-not (Test-Path (Join-Path $front "dist\index.html"))) {
    Push-Location $front
    & npm.cmd run build *> (Join-Path $logDir "build.log")
    Pop-Location
}

$backend = $null
$preview = $null
while ($true) {
    if ($null -eq $backend -or $backend.HasExited) {
        $backend = Start-Part "backend" (Join-Path $root "backend\.venv\Scripts\uvicorn.exe") `
            @("cardplatform.api:app", "--host", "127.0.0.1", "--port", "8000") $root
    }
    if ($null -eq $preview -or $preview.HasExited) {
        $preview = Start-Part "preview" (Join-Path $env:SystemRoot "System32\cmd.exe") `
            @("/c", "npx.cmd", "vite", "preview", "--host", "127.0.0.1", "--port", "4173", "--strictPort") $front
    }
    Start-Sleep -Seconds 15
}
