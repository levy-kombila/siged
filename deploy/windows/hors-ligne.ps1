# Retire SIGED d'Internet (l'application reste disponible sur https://localhost).
#   powershell -ExecutionPolicy Bypass -File deploy\windows\hors-ligne.ps1
Set-Location (Join-Path $PSScriptRoot "..\..")
docker compose --profile public stop tunnel
Write-Host "Tunnel arrêté : SIGED n'est plus accessible depuis Internet."
