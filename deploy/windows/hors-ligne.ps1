# Retire GEDarchive d'Internet (l'application reste disponible sur https://localhost).
#   powershell -ExecutionPolicy Bypass -File deploy\windows\hors-ligne.ps1
Set-Location (Join-Path $PSScriptRoot "..\..")
# rm -s : arrête ET supprime le conteneur, pour qu'aucune ancienne adresse ne reste dans ses journaux
docker compose --profile public rm -sf tunnel
Write-Host "Tunnel arrêté : GEDarchive n'est plus accessible depuis Internet."
