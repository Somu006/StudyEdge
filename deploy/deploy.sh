#!/bin/bash
# =============================================================
#  deploy.sh — MachineWhisperer one-command deploy
#  Usage: bash deploy.sh
#  Run on EC2: /home/ubuntu/AI-Compressor-Predictive-Maintenance/
# =============================================================

set -e  # exit on any error

PROJECT_DIR="/home/ubuntu/AI-Compressor-Predictive-Maintenance"
VENV="$PROJECT_DIR/venv/bin"
FRONTEND_DIR="$PROJECT_DIR/Frontend"
BACKEND_DIR="$PROJECT_DIR/backend"
SIMULATOR_DIR="$PROJECT_DIR/machine_simulator"

PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "54.89.167.234")

echo ""
echo "============================================================="
echo "  MachineWhisperer — Deployment Script"
echo "============================================================="
echo ""

# ── Step 1: Pull latest code ──────────────────────────────────────
echo "[1/5] Pulling latest code from GitHub..."
cd "$PROJECT_DIR"
git pull origin main
echo "      ✅ Code updated."
echo ""

# ── Step 2: Install/update Python dependencies ───────────────────
echo "[2/5] Installing Python dependencies..."
"$VENV/pip" install -r "$BACKEND_DIR/requirements.txt" --quiet
"$VENV/pip" install -r "$SIMULATOR_DIR/requirements.txt" --quiet
echo "      ✅ Python dependencies up to date."
echo ""

# ── Step 3: Rebuild frontend ──────────────────────────────────────
echo "[3/5] Rebuilding frontend..."
cd "$FRONTEND_DIR"
npm install --silent
npx vite build --logLevel warn
echo "      ✅ Frontend built → Frontend/dist/"
echo ""

# ── Step 4: Restart all 3 services ───────────────────────────────
echo "[4/5] Restarting services..."
sudo systemctl daemon-reload
sudo systemctl restart machinewhisperer-simulator
sleep 2
sudo systemctl restart machinewhisperer-backend
sleep 2
sudo systemctl restart machinewhisperer-frontend
sleep 3
echo "      ✅ All services restarted."
echo ""

# ── Step 5: Verify all 3 are running ─────────────────────────────
echo "[5/5] Verifying services..."
echo ""

ALL_OK=true

check_service() {
    local name=$1
    local port=$2
    local label=$3

    # systemd status
    if systemctl is-active --quiet "$name"; then
        svc_status="running"
    else
        svc_status="STOPPED"
        ALL_OK=false
    fi

    # HTTP reachability
    if curl -sf --max-time 5 "http://localhost:$port" > /dev/null 2>&1; then
        http_status="reachable"
    else
        http_status="not responding"
        ALL_OK=false
    fi

    if [ "$svc_status" = "running" ] && [ "$http_status" = "reachable" ]; then
        echo "      ✅  $label (port $port) — $svc_status, $http_status"
    else
        echo "      ❌  $label (port $port) — $svc_status, $http_status"
    fi
}

check_service "machinewhisperer-simulator" "9000" "Simulator"
check_service "machinewhisperer-backend"   "8000" "Backend  "
check_service "machinewhisperer-frontend"  "3000" "Frontend "

echo ""
echo "============================================================="
if [ "$ALL_OK" = true ]; then
    echo "  ✅  DEPLOYMENT COMPLETE — all services running"
else
    echo "  ⚠️   DEPLOYMENT DONE — some services need attention"
    echo "  Run: sudo journalctl -u machinewhisperer-backend -n 50"
fi
echo "============================================================="
echo ""
echo "  Frontend:  http://$PUBLIC_IP:3000"
echo "  API:       http://$PUBLIC_IP:8000"
echo "  API Docs:  http://$PUBLIC_IP:8000/docs"
echo "  Simulator: http://$PUBLIC_IP:9000"
echo ""
echo "  GitHub:    https://github.com/Somu006/AI-Compressor-Predictive-Maintenance"
echo "============================================================="
echo ""
