#!/usr/bin/env bash
# ============================================================
# SpaceCaptain — Selbstsigniertes Zertifikat generieren
# Verwendung:  bash gencert.sh <hostname-oder-ip>
# Beispiel:    bash gencert.sh spacecaptain.local
#              bash gencert.sh 192.168.1.100
# ============================================================
set -euo pipefail

DOMAIN="${1:-spacecaptain.local}"
CERT_DIR="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$CERT_DIR"

echo "Generiere Zertifikat für: $DOMAIN"

openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 \
    -nodes \
    -keyout "$CERT_DIR/key.pem" \
    -out    "$CERT_DIR/cert.pem" \
    -subj   "/CN=$DOMAIN" \
    -addext "subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"

chmod 600 "$CERT_DIR/key.pem"
chmod 644 "$CERT_DIR/cert.pem"

echo ""
echo "Zertifikat erstellt (gültig 10 Jahre):"
echo "  $CERT_DIR/cert.pem"
echo "  $CERT_DIR/key.pem"
echo ""
echo "Zum Aktivieren:"
echo "  docker compose up -d"
echo ""
echo "Zertifikat erneuern oder tauschen:"
echo "  1. Neue cert.pem + key.pem in certs/ ablegen"
echo "  2. docker exec spacecaptain_proxy nginx -s reload"
