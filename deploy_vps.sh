#!/bin/bash
set -e

echo "============================================"
echo " Alchemical Trading Command Center"
echo " VPS Deployment Script (Ubuntu 24.04)"
echo "============================================"

APP_DIR="/opt/alchemical-trading"
APP_USER="alchemist"
VENV_DIR="$APP_DIR/venv"

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root: sudo bash deploy_vps.sh"
  exit 1
fi

echo "[1/7] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3.12 python3.12-venv python3-pip git ufw nginx

echo "[2/7] Creating app user and directory..."
id -u $APP_USER &>/dev/null || useradd -r -m -s /bin/bash $APP_USER
mkdir -p $APP_DIR
chown $APP_USER:$APP_USER $APP_DIR

echo "[3/7] Copying application files..."
cp -r app.py run.py healthcheck.py main.py requirements.txt trading/ $APP_DIR/
mkdir -p $APP_DIR/trading/data
if [ -f trading/data/trading_framework.md ]; then
  cp trading/data/trading_framework.md $APP_DIR/trading/data/
fi
chown -R $APP_USER:$APP_USER $APP_DIR

echo "[4/7] Setting up Python virtual environment..."
sudo -u $APP_USER python3.12 -m venv $VENV_DIR
sudo -u $APP_USER $VENV_DIR/bin/pip install --upgrade pip -q
sudo -u $APP_USER $VENV_DIR/bin/pip install -r $APP_DIR/requirements.txt -q

echo "[5/7] Creating environment file..."
if [ ! -f $APP_DIR/.env ]; then
  cat > $APP_DIR/.env << 'ENVEOF'
# === REQUIRED: Alpaca Paper Trading ===
ALPACA_API_KEY=your_alpaca_api_key_here
ALPACA_SECRET_KEY=your_alpaca_secret_key_here

# === REQUIRED: Claude AI Brain ===
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# === Dashboard Authentication (set both to enable login gate) ===
DASH_USER=admin
DASH_PASS=changeme_strong_password

# === Optional: NTFY Push Notifications ===
# NTFY_TOPIC=your-unique-topic-name

# === Server Config ===
PORT=5000
ENVEOF
  echo "  -> Created $APP_DIR/.env — EDIT THIS with your real API keys!"
else
  echo "  -> .env already exists, skipping."
fi
chown $APP_USER:$APP_USER $APP_DIR/.env
chmod 600 $APP_DIR/.env

echo "[6/7] Creating systemd service..."
cat > /etc/systemd/system/alchemical-trading.service << SERVICEEOF
[Unit]
Description=Alchemical Trading Command Center
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_DIR/bin/python run.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable alchemical-trading

echo "[7/7] Configuring Nginx reverse proxy..."
cat > /etc/nginx/sites-available/alchemical-trading << 'NGINXEOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
        proxy_buffering off;
    }

    location /_stcore/health {
        proxy_pass http://127.0.0.1:5000/_stcore/health;
    }

    location /health {
        proxy_pass http://127.0.0.1:8099/health;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/alchemical-trading /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx

echo ""
echo "============================================"
echo " Deployment Complete!"
echo "============================================"
echo ""
echo " NEXT STEPS:"
echo ""
echo " 1. Edit your API keys:"
echo "    nano $APP_DIR/.env"
echo ""
echo " 2. Start the service:"
echo "    sudo systemctl start alchemical-trading"
echo ""
echo " 3. Check status:"
echo "    sudo systemctl status alchemical-trading"
echo ""
echo " 4. View logs:"
echo "    sudo journalctl -u alchemical-trading -f"
echo ""
echo " 5. Access dashboard:"
echo "    http://YOUR_SERVER_IP"
echo ""
echo " 6. (Optional) Add SSL with Let's Encrypt:"
echo "    apt install certbot python3-certbot-nginx"
echo "    certbot --nginx -d yourdomain.com"
echo ""
echo "============================================"
