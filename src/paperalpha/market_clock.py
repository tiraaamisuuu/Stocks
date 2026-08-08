from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pandas_market_calendars as mcal

from paperalpha.domain import SessionInfo


class MarketClock:
    def __init__(self, exchange: str = "NYSE") -> None:
        self.calendar = mcal.get_calendar(exchange)

    def session_info(self, now: datetime | None = None) -> SessionInfo:
        moment = now or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        moment_stamp = pd.Timestamp(moment).tz_convert("UTC")
        schedule = self.calendar.schedule(
            start_date=(moment.date() - timedelta(days=1)).isoformat(),
            end_date=(moment.date() + timedelta(days=10)).isoformat(),
        )

        todays_row = _row_for_date(schedule, moment.date())
        future_opens = schedule.loc[schedule["market_open"] > moment_stamp, "market_open"]
        next_open = future_opens.iloc[0].to_pydatetime() if not future_opens.empty else None

        if todays_row is None:
            return SessionInfo("closed", "Market closed", None, None, next_open)

        market_open = todays_row["market_open"].to_pydatetime()
        market_close = todays_row["market_close"].to_pydatetime()
        if moment < market_open:
            state, label = "pre_market", "Pre-market"
        elif moment <= market_close:
            state, label = "open", "Market open"
        else:
            state, label = "after_hours", "Market closed for the day"
        return SessionInfo(state, label, market_open, market_close, next_open)

    def session_bounds(self, session_date: str | date) -> tuple[datetime, datetime] | None:
        day = date.fromisoformat(session_date) if isinstance(session_date, str) else session_date
        schedule = self.calendar.schedule(start_date=day.isoformat(), end_date=day.isoformat())
        row = _row_for_date(schedule, day)
        if row is None:
            return None
        return row["market_open"].to_pydatetime(), row["market_close"].to_pydatetime()


def _row_for_date(schedule: pd.DataFrame, day: date) -> pd.Series | None:
    if schedule.empty:
        return None
    matches = schedule[schedule.index.date == day]
    return matches.iloc[0] if not matches.empty else None
