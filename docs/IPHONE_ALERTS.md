# iPhone paper-trade alerts

PaperAlpha can send iPhone notifications without building or signing a native iOS application.
The laptop runs the research and paper-trading process; the open-source ntfy iOS app receives its
HTTPS messages.

Every alert is a **simulated paper-trade event**. PaperAlpha has no brokerage credentials and
cannot place a real order.

## Set up the iPhone

1. Install [ntfy from the App Store](https://apps.apple.com/app/ntfy/id1625396347).
2. On the laptop, clone or update PaperAlpha and open PowerShell in the repository.
3. Run:

   ```powershell
   .\scripts\start_paper_day.ps1 -Budget 1000 -Fractional
   ```

4. On first use, the script prints a randomly generated topic beginning with `paperalpha-`.
5. In ntfy, add a subscription using server `https://ntfy.sh` and the exact generated topic.
6. Return to PowerShell and press Enter. A test notification should arrive immediately.

The generated topic is effectively a password. It is saved only in `state/notifications.json`,
which Git ignores. Do not put the topic in a screenshot, README, commit, or public chat.

## What happens during the session

- Within two hours of the regular open, the laptop performs the full-market scan and sends a
  **watchlist** alert. This explicitly says to wait.
- After the regular market opens, it fetches a fresh price, creates one local paper position, and
  sends a **PAPER BUY** alert.
- It records prices and evaluates exit rules every minute. It sends a single **PAPER SELL** as soon
  as the 3% hard stop, 5% take-profit, trailing stop, or strong reversal rule fires. The message
  includes the exact reason, exit price, and paper P/L.
- If no intraday exit fires, it exits at the official close and writes the JSON/CSV report.
- It does not send hourly status noise; notifications describe `WAIT`, `BUY`, or `SELL` actions.
- The command exits only after the closing position and report have been persisted.

If the laptop or internet connection drops, restart the same command. The SQLite ledger prevents
it from opening a second position for the same session.

## Useful commands

Configure notifications manually:

```powershell
paperalpha-notify setup
paperalpha-notify test
```

Run without fractional shares or with a different paper budget:

```powershell
paperalpha-day --budget 2500
```

Use a GBP-denominated budget that is converted at the simulated entry time:

```powershell
paperalpha-day --budget-gbp 150 --fractional
```

For an always-on Windows laptop, follow the [server setup guide](SERVER_SETUP.md).

If the Streamlit dashboard is available at a safe URL, attach it to notifications:

```powershell
paperalpha-day --budget 1000 --dashboard-url "https://your-private-dashboard.example"
```

Do not expose Streamlit directly to the public internet. For a future permanent installation,
put the dashboard behind authenticated HTTPS and configure a private, authenticated ntfy server.
