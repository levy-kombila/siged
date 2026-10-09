#!/bin/sh
# Certificat auto-signé pour les tests. En production : certificat de l'autorité interne ou Let's Encrypt.
set -e
mkdir -p "$(dirname "$0")/../nginx/certs"
cd "$(dirname "$0")/../nginx/certs"
openssl req -x509 -newkey rsa:3072 -sha256 -days 365 -nodes \
  -keyout siged.key -out siged.crt -subj "/CN=siged.local" \
  -addext "subjectAltName=DNS:siged.local,DNS:localhost,IP:127.0.0.1"
echo "Certificat généré dans deploy/nginx/certs/"
