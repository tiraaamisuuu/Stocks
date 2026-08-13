# Always-on Windows server setup

PaperAlpha can run continuously on an old Windows laptop. The laptop performs the research and
stores the paper ledger; the ntfy app only receives its notifications. No brokerage account or
real-money credentials are involved.

## First installation

Install Git and Python 3.11 or newer on the server, then open PowerShell and run:

```powershell
git clone https://github.com/tiraaamisuuu/Stocks.git
cd Stocks
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_server.ps1 -BudgetGbp 150
```

The first installation creates an isolated Python environment and a new private ntfy topic. Add
that exact topic in the ntfy iPhone app, then return to PowerShell and press Enter. The installer
sends a test notification before it creates and starts the scheduled task.

The task:

- starts whenever that Windows user signs in;
- has a noon daily trigger as a fallback;
- restarts five minutes after a failure;
- stays online across market days;
- converts GBP 150 to USD at the exchange rate fetched when each paper position opens;
- uses fractional paper shares, prevents overlapping positions, and defaults to five entries per
  market session.

The Windows account must remain signed in. The screen can be locked, but signing out stops an
interactive scheduled task. Disable sleep and hibernation on the server and leave its internet
connection enabled.

## Check or control it

Show task state:

```powershell
Get-ScheduledTask -TaskName "PaperAlpha Server"
```

Follow the live log:

```powershell
Get-Content .\state\paperalpha-server.log -Wait
```

Restart it:

```powershell
Stop-ScheduledTask -TaskName "PaperAlpha Server"
Start-ScheduledTask -TaskName "PaperAlpha Server"
```

Update the code and reapply the task configuration:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_server.ps1 -BudgetGbp 150
```

Remove only the scheduled task while keeping the database and reports:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows_server.ps1
```

The desktop `PaperAlpha.exe` is the interactive dashboard. It does not need to be open for the
server runner to operate.
