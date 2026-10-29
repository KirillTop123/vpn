#!/usr/bin/env bash
# All-in-one install on ONE server (e.g. Oracle Cloud Always Free): panel + Telegram bot + VPN node.
# No domain needed: uses <ip>.sslip.io with a free Let's Encrypt certificate.
#
#   curl -fsSL https://raw.githubusercontent.com/KirillTop123/vpn/claude/vpn-service/deploy/oneclick.sh | sudo bash -s -- <BOT_TOKEN> <YOUR_TELEGRAM_ID> [BRAND_NAME]
#
# Safe to re-run: keeps existing .env, database and node.
set -euo pipefail

BOT_TOKEN="${1:?usage: oneclick.sh <BOT_TOKEN> <TELEGRAM_ID> [BRAND_NAME]}"
ADMIN_ID="${2:?usage: oneclick.sh <BOT_TOKEN> <TELEGRAM_ID> [BRAND_NAME]}"
BRAND="${3:-MyVPN}"
REPO_URL="${REPO_URL:-https://github.com/KirillTop123/vpn.git}"
REPO_BRANCH="${REPO_BRANCH:-claude/vpn-service}"
DIR="${DIR:-/opt/vpn}"
PANEL_PORT=2096   # 443/8443 are taken by the VPN itself

if [[ $EUID -ne 0 ]]; then echo "Запустите от root (sudo)"; exit 1; fi

echo "==> Пакеты и Docker"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates openssl python3 iptables >/dev/null
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
systemctl enable --now docker >/dev/null

echo "==> Код"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/../docker-compose.yml" ]]; then
  DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [[ -d "$DIR/.git" ]]; then
  git -C "$DIR" pull -q --ff-only || true
else
  git clone -q -b "$REPO_BRANCH" "$REPO_URL" "$DIR"
fi
cd "$DIR"

IP="$(curl -4 -fsS --max-time 10 https://api.ipify.org || curl -4 -fsS --max-time 10 https://ifconfig.me)"
DOMAIN="${IP//./-}.sslip.io"
PANEL_URL="https://$DOMAIN:$PANEL_PORT"
CC="$(curl -fsS --max-time 10 "https://ipinfo.io/$IP/country" 2>/dev/null | tr -d '[:space:]' || true)"
FLAG="$(python3 -c "import sys;c=sys.argv[1].upper();print(''.join(chr(0x1F1E6+ord(x)-65) for x in c) if len(c)==2 and c.isalpha() else '🌐')" "${CC:-}")"

echo "==> Настройки (.env)"
if [[ ! -f .env ]]; then
  ADMIN_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=')"
  cat >.env <<EOF
PANEL_DOMAIN=$DOMAIN
PANEL_PORT=$PANEL_PORT
PANEL_URL=$PANEL_URL
ADMIN_PASSWORD=$ADMIN_PASSWORD
SECRET_KEY=$(openssl rand -hex 32)
BRAND_NAME=$BRAND
SUPPORT_URL=tg://user?id=$ADMIN_ID
ANNOUNCE=
SUB_UPDATE_HOURS=6
BOT_TOKEN=$BOT_TOKEN
ADMIN_TG_IDS=$ADMIN_ID
TRIAL_DAYS=3
REFERRAL_BONUS_DAYS=7
PLANS=30:150,90:400,180:750,365:1400
EOF
  chmod 600 .env
fi
ADMIN_PASSWORD="$(grep '^ADMIN_PASSWORD=' .env | cut -d= -f2-)"

echo "==> Порты (iptables для Oracle Cloud)"
for p in 80 $PANEL_PORT 443 8443; do
  iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport $p -j ACCEPT
done
command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1 || true

echo "==> Запуск панели и бота"
docker compose up -d --build
for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 2
done

echo "==> VPN-нода на этом же сервере"
TOKEN="$(docker compose exec -T panel python -m app.cli add-node --name "${CC:-Server}" --flag "$FLAG" --address "$IP" | tail -1)"
AGENT_SRC="$DIR/node/agent.py" bash "$DIR/node/install.sh" http://127.0.0.1:8000 "$TOKEN"

BOT_NAME="$(curl -fsS "https://api.telegram.org/bot$BOT_TOKEN/getMe" | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['username'])" 2>/dev/null || echo '?')"

cat >/root/vpn-credentials.txt <<EOF
Админка:  $PANEL_URL/admin
Пароль:   $ADMIN_PASSWORD
Бот:      https://t.me/$BOT_NAME
Папка:    $DIR
EOF
chmod 600 /root/vpn-credentials.txt

echo
echo "================================================================"
echo "✅ Готово! Всё работает автономно и переживает перезагрузку."
cat /root/vpn-credentials.txt
echo
echo "Откройте бота, нажмите /start → «Попробовать бесплатно»."
echo "Данные сохранены в /root/vpn-credentials.txt"
echo "================================================================"
