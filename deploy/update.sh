#!/usr/bin/env bash
# Deploy the latest main branch to the running EC2 instance (as ubuntu user).
set -euo pipefail

APP_DIR=/home/ubuntu/back-end-simulation
cd "$APP_DIR"

git pull origin main
source venv/bin/activate
pip install -r requirements.txt
mkdir -p data/runs_v2
sudo systemctl restart back-end-simulation

echo ""
echo "✅ Deployed and restarted. App running at https://backendsim.com"
