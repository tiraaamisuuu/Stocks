#!/usr/bin/env bash
set -euo pipefail

service_name="${1:-paperalpha}"
if [[ $EUID -ne 0 ]]; then
    printf 'Run this command as root.\n' >&2
    exit 1
fi
if [[ ! $service_name =~ ^[a-zA-Z0-9_-]+$ ]]; then
    printf 'Invalid service name.\n' >&2
    exit 2
fi

systemctl disable --now "$service_name.service" 2>/dev/null || true
rm -f -- "/etc/systemd/system/$service_name.service"
systemctl daemon-reload
printf 'Removed %s.service. PaperAlpha data and reports were kept.\n' "$service_name"
