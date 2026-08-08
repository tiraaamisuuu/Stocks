# Public-disclosure signals

`trader_signals.csv` is intentionally empty. Add only lawful, publicly disclosed
transactions and record the time at which the disclosure became available—not the
underlying trade date. This prevents look-ahead bias.

Columns:

- `ticker`: US ticker symbol
- `disclosed_at`: ISO-8601 timestamp, ideally with timezone
- `actor`: disclosed investor, institution, or insider
- `side`: `buy` or `sell`
- `notional_usd`: disclosed or midpoint estimated value in US dollars
- `source_url`: URL to the public filing or disclosure

Example (illustrative only; do not treat it as real data):

```csv
ticker,disclosed_at,actor,side,notional_usd,source_url
XYZ,2026-01-15T17:30:00Z,Example filer,buy,50000,https://example.com/filing
```
