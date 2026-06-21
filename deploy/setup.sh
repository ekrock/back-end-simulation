#!/usr/bin/env bash
# Run once on a fresh Ubuntu 22.04 EC2 instance (as ubuntu user).
# Sets up the app with HTTP only. Run setup-https.sh afterwards for TLS.
set -euo pipefail

APP_DIR=/home/ubuntu/back-end-simulation

# ── System packages ──────────────────────────────────────────────────────────
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-dev \
    nginx git

# ── Clone / pull repo ────────────────────────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    echo "Repo exists — pulling latest..."
    cd "$APP_DIR"
    git pull
else
    git clone git@github.com:ekrock/back-end-simulation.git "$APP_DIR"
    cd "$APP_DIR"
fi

# ── Python venv + dependencies ───────────────────────────────────────────────
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

# ── Data + log directories ───────────────────────────────────────────────────
mkdir -p data/runs logs

# ── .env (edit credentials before running) ───────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  Edit $APP_DIR/.env and set real ADMIN/DEMO credentials, then restart the service."
fi

# ── systemd service ──────────────────────────────────────────────────────────
sudo cp deploy/back-end-simulation.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable back-end-simulation
sudo systemctl restart back-end-simulation

# ── nginx HTTP config ─────────────────────────────────────────────────────────
sudo cp deploy/nginx-http.conf /etc/nginx/sites-available/back-end-simulation
sudo ln -sf /etc/nginx/sites-available/back-end-simulation \
            /etc/nginx/sites-enabled/back-end-simulation
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "✅ Setup complete. App running at http://backendsim.com"
echo "   Next: run deploy/setup-https.sh to enable HTTPS."
