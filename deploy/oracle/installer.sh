#!/usr/bin/env bash
# Préparation d'une VM Oracle Cloud « Always Free » (Ubuntu 24.04, Ampere A1 ARM64) pour SIGED.
# Usage (sur la VM, une seule fois) :   bash deploy/oracle/installer.sh
# Idempotent : peut être relancé sans danger.
set -euo pipefail
APT="sudo DEBIAN_FRONTEND=noninteractive apt-get -y -q"

echo "==> 1/6 Mise à jour du système"
$APT update
$APT upgrade
$APT install git curl ca-certificates python3 netfilter-persistent iptables-persistent

echo "==> 2/6 Fuseau horaire"
sudo timedatectl set-timezone Africa/Libreville || true

echo "==> 3/6 Docker Engine + Compose"
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker

echo "==> 4/6 Pare-feu de la VM : ouverture des ports 80 et 443"
# Les images Ubuntu d'Oracle bloquent tout sauf SSH via iptables (règle REJECT finale).
for rule in "-p tcp --dport 80" "-p tcp --dport 443" "-p udp --dport 443"; do
    # shellcheck disable=SC2086
    sudo iptables -C INPUT $rule -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null \
        || sudo iptables -I INPUT 1 $rule -m conntrack --ctstate NEW -j ACCEPT
done
sudo netfilter-persistent save

echo "==> 5/6 Fichier d'échange (swap) de 2 Go (sécurité pour LibreOffice / OCR)"
if ! swapon --show | grep -q /swapfile; then
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile && sudo swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "==> 6/6 Mises à jour de sécurité automatiques"
$APT install unattended-upgrades
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

echo
echo "Terminé. DÉCONNECTEZ-VOUS puis reconnectez-vous (exit, puis ssh) pour utiliser docker sans sudo."
echo "Ensuite : créez le fichier .env (docs/deploiement_oracle.md, étape 6) puis : bash deploy/oracle/demarrer.sh"
