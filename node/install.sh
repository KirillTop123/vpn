#!/usr/bin/env bash
# One-command node setup. Usage (copy the exact line from the node page in the admin panel):
#   curl -fsSL https://PANEL/node/install.sh | sudo bash -s -- https://PANEL NODE_TOKEN
set -euo pipefail

PANEL_URL="${1:?panel url required}"
NODE_TOKEN="${2:?node token required}"
PANEL_URL="${PANEL_URL%/}"

if [[ $EUID -ne 0 ]]; then echo "Run as root (sudo)"; exit 1; fi

echo "==> Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl unzip python3 ca-certificates >/dev/null

echo "==> Installing / updating Xray-core"
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install-geodata

echo "==> Network tuning (BBR, bigger buffers)"
cat >/etc/sysctl.d/99-vpn.conf <<'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_mtu_probing = 1
fs.file-max = 1000000
EOF
sysctl --system >/dev/null || true

echo "==> Installing node agent"
mkdir -p /opt/vpn-agent
if [[ -n "${AGENT_SRC:-}" && -f "$AGENT_SRC" ]]; then
  cp "$AGENT_SRC" /opt/vpn-agent/agent.py
else
  curl -fsSL "$PANEL_URL/node/agent.py" -o /opt/vpn-agent/agent.py
fi
cat >/etc/vpn-agent.env <<EOF
PANEL_URL=$PANEL_URL
NODE_TOKEN=$NODE_TOKEN
EOF
chmod 600 /etc/vpn-agent.env

cat >/etc/systemd/system/vpn-agent.service <<'EOF'
[Unit]
Description=VPN node agent (syncs Xray config with panel)
After=network-online.target
Wants=network-online.target

[Service]
EnvironmentFile=/etc/vpn-agent.env
ExecStart=/usr/bin/python3 /opt/vpn-agent/agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Keep geo databases fresh (used by bridge routing).
cat >/etc/cron.weekly/xray-geodata <<'EOF'
#!/bin/sh
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install-geodata && systemctl restart xray
EOF
chmod +x /etc/cron.weekly/xray-geodata

if command -v ufw >/dev/null && ufw status | grep -q active; then
  echo "==> Opening ports in ufw"
  ufw allow 443/tcp >/dev/null; ufw allow 8443/tcp >/dev/null
fi
# Oracle Cloud Ubuntu images ship iptables rules that reject everything except SSH.
if iptables -S INPUT 2>/dev/null | grep -q -- "-j REJECT"; then
  echo "==> Opening ports in iptables"
  for p in 443 8443; do
    iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport $p -j ACCEPT
  done
  command -v netfilter-persistent >/dev/null && netfilter-persistent save >/dev/null 2>&1 || true
fi

systemctl daemon-reload
systemctl enable --now xray >/dev/null 2>&1 || true
systemctl enable vpn-agent >/dev/null
systemctl restart vpn-agent

echo
echo "✅ Node installed. It will appear as online in the panel within ~30 seconds."
echo "   Logs: journalctl -u vpn-agent -f   |   journalctl -u xray -f"
