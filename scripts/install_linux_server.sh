#!/usr/bin/env bash
set -euo pipefail

service_user=""
budget_gbp="150"
service_name="paperalpha"
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

while (($#)); do
    case "$1" in
        --user)
            service_user="${2:?--user requires a value}"
            shift 2
            ;;
        --budget-gbp)
            budget_gbp="${2:?--budget-gbp requires a value}"
            shift 2
            ;;
        --service-name)
            service_name="${2:?--service-name requires a value}"
            shift 2
            ;;
        *)
            printf 'Unknown argument: %s\n' "$1" >&2
            exit 2
            ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    printf 'Run this installer as root, for example with sudo or su.\n' >&2
    exit 1
fi
if [[ -z $service_user ]] || ! id "$service_user" >/dev/null 2>&1; then
    printf 'Provide an existing Linux account with --user.\n' >&2
    exit 2
fi
if [[ ! $budget_gbp =~ ^[0-9]+([.][0-9]+)?$ ]] || \
    ! awk -v value="$budget_gbp" 'BEGIN { exit !(value > 0) }'; then
    printf '%s\n' '--budget-gbp must be a positive number.' >&2
    exit 2
fi
if [[ ! $service_name =~ ^[a-zA-Z0-9_-]+$ ]]; then
    printf '%s\n' '--service-name may contain only letters, numbers, underscores, and hyphens.' >&2
    exit 2
fi

service_group="$(id -gn "$service_user")"
service_home="$(getent passwd "$service_user" | cut -d: -f6)"
venv_python="$project_dir/.venv/bin/python"
notification_config="$project_dir/state/notifications.json"
unit_path="/etc/systemd/system/$service_name.service"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y git python3-venv ca-certificates
install -d -m 700 -o "$service_user" -g "$service_group" "$project_dir/state"

if [[ ! -x $venv_python ]]; then
    runuser -u "$service_user" -- python3 -m venv "$project_dir/.venv"
fi
runuser -u "$service_user" -- env HOME="$service_home" \
    "$venv_python" -m pip install --upgrade pip
runuser -u "$service_user" -- env HOME="$service_home" \
    "$venv_python" -m pip install -e "$project_dir"

if [[ ! -f $notification_config ]]; then
    runuser -u "$service_user" -- env HOME="$service_home" \
        "$venv_python" -m paperalpha.notifications setup --config "$notification_config"
    printf '\nSubscribe the iPhone ntfy app to the topic printed above.\n'
    read -r -p 'Press Enter after the topic is subscribed on the phone: '
fi
chmod 600 "$notification_config"
chown "$service_user:$service_group" "$notification_config"
runuser -u "$service_user" -- env HOME="$service_home" \
    "$venv_python" -m paperalpha.notifications test --config "$notification_config"

cat >"$unit_path" <<EOF
[Unit]
Description=PaperAlpha continuous paper-trading alerts
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$service_user
Group=$service_group
WorkingDirectory=$project_dir
Environment=PYTHONUNBUFFERED=1
ExecStart=$venv_python -m paperalpha.day_trader --budget-gbp $budget_gbp --fractional --continuous --interval 60 --notification-config $notification_config
Restart=on-failure
RestartSec=30s
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$project_dir/state

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$unit_path"
systemctl daemon-reload
systemctl enable --now "$service_name.service"

printf '\nPaperAlpha is installed and running.\n'
printf 'Service: %s.service\n' "$service_name"
printf 'Budget:  GBP %s, converted to USD at each simulated entry\n' "$budget_gbp"
printf 'Status:  systemctl status %s --no-pager\n' "$service_name"
printf 'Logs:    journalctl -u %s -f\n' "$service_name"
