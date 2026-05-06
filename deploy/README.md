# MachineWhisperer — EC2 Deployment Files

## One-time setup (run once on EC2)

```bash
# 1. Copy systemd service files
sudo cp deploy/machinewhisperer-*.service /etc/systemd/system/

# 2. Reload systemd and enable services (auto-start on reboot)
sudo systemctl daemon-reload
sudo systemctl enable machinewhisperer-simulator
sudo systemctl enable machinewhisperer-backend
sudo systemctl enable machinewhisperer-frontend

# 3. Start all services
sudo systemctl start machinewhisperer-simulator
sudo systemctl start machinewhisperer-backend
sudo systemctl start machinewhisperer-frontend

# 4. Make scripts executable
chmod +x deploy/deploy.sh deploy/health_check.sh
```

## Daily use

| Command | What it does |
|---|---|
| `bash deploy/deploy.sh` | Pull latest code, rebuild frontend, restart all services |
| `bash deploy/health_check.sh` | Check all ports, services, DynamoDB, SNS, S3 |
| `sudo systemctl status machinewhisperer-backend` | Check backend logs |
| `sudo journalctl -u machinewhisperer-backend -f` | Tail backend logs live |
| `sudo systemctl restart machinewhisperer-backend` | Restart backend only |

## Live URLs

| Service | URL |
|---|---|
| Frontend | http://54.89.167.234:3000 |
| API | http://54.89.167.234:8000 |
| API Docs | http://54.89.167.234:8000/docs |
| Simulator | http://54.89.167.234:9000 |
