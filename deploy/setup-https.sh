#!/usr/bin/env bash
# Run after setup.sh once the domain backendsim.com points to this server's IP.
# Obtains a Let's Encrypt certificate and switches nginx to HTTPS.
set -euo pipefail

APP_DIR=/home/ubuntu/back-end-simulation

# ── Install certbot ──────────────────────────────────────────────────────────
sudo apt-get install -y certbot python3-certbot-nginx

# ── Obtain certificate ────────────────────────────────────────────────────────
sudo certbot --nginx -d backendsim.com -d www.backendsim.com \
    --non-interactive --agree-tos --email eric4growth@gmail.com

# ── Switch to HTTPS nginx config ─────────────────────────────────────────────
sudo cp "$APP_DIR/deploy/nginx-https.conf" \
        /etc/nginx/sites-available/back-end-simulation
sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "✅ HTTPS enabled. App running at https://backendsim.com"
