#!/usr/bin/env bash
# NetTrace — Uninstaller
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
info() { echo -e "${GREEN}[+]${NC} $1"; }

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Run as root: sudo bash uninstall.sh${NC}"
    exit 1
fi

read -p "This will remove NetTrace completely. Continue? [y/N] " -n 1 -r
echo
[[ ! $REPLY =~ ^[Yy]$ ]] && exit 0

info "Stopping services..."
systemctl stop nettrace 2>/dev/null || true
systemctl disable nettrace 2>/dev/null || true

info "Stopping Docker containers..."
cd /opt/nettrace && docker-compose down -v 2>/dev/null || true

info "Removing systemd service..."
rm -f /etc/systemd/system/nettrace.service
systemctl daemon-reload

info "Removing nginx config..."
rm -f /etc/nginx/sites-enabled/nettrace
rm -f /etc/nginx/sites-available/nettrace
systemctl restart nginx 2>/dev/null || true

info "Removing application files..."
rm -rf /opt/nettrace

info "Removing service user..."
userdel nettrace 2>/dev/null || true

info "NetTrace removed."
