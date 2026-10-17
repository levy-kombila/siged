# Met GEDarchive en ligne depuis ce PC (Cloudflare Quick Tunnel, gratuit, sans compte).
# Usage (dans D:\Django\siged) :
#   powershell -ExecutionPolicy Bypass -File deploy\windows\en-ligne.ps1
# L'adresse n'est annoncée qu'une fois le site réellement joignable depuis Internet
# (tunnel connecté, nom DNS publié, /health qui répond).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")

if (-not (Test-Path ".env")) { Write-Host "ERREUR : fichier .env absent (voir docs/guide_secrets.md)" -ForegroundColor Red; exit 1 }

Write-Host "Démarrage de GEDarchive et du tunnel public (reconstruction de l'image si le code a changé)..."
docker compose --profile public up -d --build
if ($LASTEXITCODE -ne 0) { Write-Host "Échec de docker compose (Docker Desktop est-il lancé ?)" -ForegroundColor Red; exit 1 }

function TunnelLogs { (docker compose --profile public logs --no-log-prefix tunnel 2>&1 | Out-String) }

# 1) Adresse publique (la plus récente des journaux du tunnel)
Write-Host "1/3 Attente de l'adresse publique (jusqu'à 60 s)..."
$url = $null
for ($i = 0; $i -lt 30 -and -not $url; $i++) {
    Start-Sleep -Seconds 2
    $found = [regex]::Matches((TunnelLogs), "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($found.Count -gt 0) { $url = $found[$found.Count - 1].Value }
}
if (-not $url) {
    Write-Host "Adresse introuvable. Diagnostic : docker compose --profile public logs tunnel" -ForegroundColor Yellow
    exit 1
}
$hostName = ([uri]$url).Host

# 2) Connexion du tunnel aux serveurs Cloudflare (message affiché APRÈS l'adresse)
Write-Host "2/3 Attente de la connexion du tunnel..."
$connected = $false
for ($i = 0; $i -lt 30 -and -not $connected; $i++) {
    $logs = TunnelLogs
    $after = $logs.Substring([Math]::Max(0, $logs.LastIndexOf($url)))
    if ($after -match "Registered tunnel connection") { $connected = $true } else { Start-Sleep -Seconds 2 }
}
if (-not $connected) {
    Write-Host "Le tunnel n'arrive pas à se connecter à Cloudflare (réseau ou pare-feu qui bloque le port 7844)." -ForegroundColor Yellow
    Write-Host "Derniers messages :" ; docker compose --profile public logs --tail 15 tunnel
    exit 1
}

# 3) Publication DNS, vérifiée auprès d'un résolveur public pour ne pas « empoisonner » le cache DNS
#    de ce PC (une adresse demandée trop tôt reste marquée « introuvable » plusieurs minutes).
Write-Host "3/3 Vérification depuis Internet..."
$resolved = $false
for ($i = 0; $i -lt 30 -and -not $resolved; $i++) {
    try { $null = Resolve-DnsName -Name $hostName -Server 1.1.1.1 -DnsOnly -Type A -ErrorAction Stop; $resolved = $true }
    catch { Start-Sleep -Seconds 2 }
}
$healthy = $false
if ($resolved) {
    for ($i = 0; $i -lt 10 -and -not $healthy; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "$url/health" -UseBasicParsing -TimeoutSec 10
            $healthy = ($r.StatusCode -eq 200)
        } catch { Start-Sleep -Seconds 3 }
    }
}

Write-Host ""
if ($healthy) {
    Write-Host "GEDarchive est en ligne : $url" -ForegroundColor Green
} else {
    Write-Host "Adresse : $url" -ForegroundColor Yellow
    if (-not $resolved) { Write-Host "Le nom n'est pas encore publié : attendez 1 à 2 minutes avant de l'ouvrir, y compris sur le téléphone." -ForegroundColor Yellow }
    else { Write-Host "Le nom est publié mais ce PC n'obtient pas de réponse (cache DNS ?). Essayez depuis le téléphone, ou exécutez « ipconfig /flushdns » en administrateur." -ForegroundColor Yellow }
}
Write-Host "Sur le téléphone : ouvrez $url/#scan (ou visez le QR code de la page Numériser sur ce PC)."
Write-Host "Si le téléphone affiche « serveur introuvable » : passez-le en mode avion 10 s puis réessayez,"
Write-Host "et désactivez le « DNS privé » ou le bloqueur de publicités s'il y en a un."
Write-Host "(adresse copiée dans le presse-papiers ; elle change à chaque redémarrage du tunnel)"
Set-Clipboard -Value $url
if ($healthy) { Start-Process $url }
