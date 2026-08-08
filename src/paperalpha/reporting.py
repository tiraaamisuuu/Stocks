from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from paperalpha.domain import PaperPosition


class SessionReporter:
    def __init__(self, report_dir: str | Path) -> None:
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def write(self, session_date: str | date, positions: list[PaperPosition]) -> tuple[Path, Path]:
        day = date.fromisoformat(session_date) if isinstance(session_date, str) else session_date
        rows = [_report_row(position) for position in positions]
        total_budget = sum(position.budget for position in positions)
        total_pnl = sum(position.pnl or 0 for position in positions)
        summary = {
            "session_date": day.isoformat(),
            "generated_at": datetime.now(UTC).isoformat(),
            "position_count": len(positions),
            "total_budget": total_budget,
            "total_pnl": total_pnl,
            "return_pct": total_pnl / total_budget * 100 if total_budget else 0.0,
            "positions": rows,
        }
        json_path = self.report_dir / f"{day.isoformat()}.json"
        csv_path = self.report_dir / f"{day.isoformat()}.csv"
        json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        return json_path, csv_path


def _report_row(position: PaperPosition) -> dict[str, object]:
    row = asdict(position)
    row["opened_at"] = position.opened_at.isoformat()
    row["closed_at"] = position.closed_at.isoformat() if position.closed_at else None
    row["invested"] = position.invested
    row.pop("rationale", None)
    return row
