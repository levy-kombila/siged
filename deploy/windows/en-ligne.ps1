# Met SIGED en ligne depuis ce PC (Cloudflare Quick Tunnel, gratuit, sans compte).
# Usage (dans D:\Django\siged) :
#   powershell -ExecutionPolicy Bypass -File deploy\windows\en-ligne.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")

if (-not (Test-Path ".env")) { Write-Host "ERREUR : fichier .env absent (voir docs/guide_secrets.md)" -ForegroundColor Red; exit 1 }

Write-Host "Démarrage de SIGED et du tunnel public..."
docker compose --profile public up -d
if ($LASTEXITCODE -ne 0) { Write-Host "Échec de docker compose (Docker Desktop est-il lancé ?)" -ForegroundColor Red; exit 1 }

Write-Host "Attente de l'adresse publique (jusqu'à 60 s)..."
$url = $null
for ($i = 0; $i -lt 30 -and -not $url; $i++) {
    Start-Sleep -Seconds 2
    $logs = (docker compose --profile public logs tunnel 2>&1 | Out-String)
    $found = [regex]::Matches($logs, "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($found.Count -gt 0) { $url = $found[$found.Count - 1].Value }
}
if (-not $url) {
    Write-Host "Adresse introuvable. Diagnostic : docker compose --profile public logs tunnel" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "SIGED est en ligne : $url" -ForegroundColor Green
Write-Host "(adresse copiée dans le presse-papiers ; elle change à chaque redémarrage du tunnel)"
Set-Clipboard -Value $url
Start-Process $url
