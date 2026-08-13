# Always-on Linux server setup

PaperAlpha can run as a locked-down systemd service on a Debian or Ubuntu server. It starts at
boot, restarts after a failure, and stays online across market days. The service does not need a
desktop session or the dashboard executable.

## Install

Clone the repository as the account that will own PaperAlpha:

```bash
git clone https://github.com/tiraaamisuuu/Stocks.git
cd Stocks
```

Run the installer as root, replacing `YOUR_USER` with that Linux account:

```bash
su -
bash /home/YOUR_USER/Stocks/scripts/install_linux_server.sh \
  --user YOUR_USER \
  --budget-gbp 150 \
  --max-trades-per-day 5
```

On first installation, the command prints a private ntfy topic. Subscribe to it in the iPhone
ntfy app, then press Enter. The installer sends a test notification and starts the service.

The service converts the GBP budget to USD at each simulated entry, uses fractional paper shares,
allows at most one open position, and caps entries at five per market session. Realized paper gains
and losses carry into the next entry. The notification topic is stored with
owner-only permissions and is excluded from Git.

## Check and maintain it

```bash
systemctl status paperalpha --no-pager
journalctl -u paperalpha -f
```

Update PaperAlpha:

```bash
cd /home/YOUR_USER/Stocks
git pull
su -
bash /home/YOUR_USER/Stocks/scripts/install_linux_server.sh \
  --user YOUR_USER \
  --budget-gbp 150 \
  --max-trades-per-day 5
```

Remove the service while keeping its database and reports:

```bash
su -
bash /home/YOUR_USER/Stocks/scripts/uninstall_linux_server.sh
```

Avoid running another PaperAlpha worker with a separate database at the same time, because that
would produce duplicate paper-trade notifications.
