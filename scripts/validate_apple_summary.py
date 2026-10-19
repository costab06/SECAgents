
"""Generate and inspect Apple's financial summary from its 10-Q."""

import json
from decimal import Decimal
from pathlib import Path

from secagent.parsing.xbrl import extract_inline_xbrl
from secagent.parsing.xbrl_normalize import normalize_xbrl
from secagent.parsing.financial_summary import (
    FinancialSummaryBuilder,
    Period,
    SummaryPeriods,
)


ROOT = Path(
    "data/filings/320193/0000320193-26-000020"
)

SOURCE = ROOT / "aapl-20260627.htm"
OUTPUT = ROOT / "financial-summary.json"


def billions(metric: dict) -> str:
    if metric["status"] != "selected":
        return metric["status"]

    value = Decimal(metric["value"]) / Decimal("1000000000")
    return f"${value:,.3f}B"


def percent(metric: dict) -> str:
    if metric["status"] != "calculated":
        return metric["status"]

    return f'{metric["value"]}%'


def main() -> None:
    raw = SOURCE.read_bytes()

    xbrl = extract_inline_xbrl(raw)
    normalized = normalize_xbrl(xbrl, raw)

    periods = SummaryPeriods(
        current_quarter=Period(
            start="2026-03-29",
            end="2026-06-27",
        ),
        prior_year_quarter=Period(
            start="2025-03-30",
            end="2025-06-28",
        ),
        current_ytd=Period(
            start="2025-09-28",
            end="2026-06-27",
        ),
        prior_year_ytd=Period(
            start="2024-09-29",
            end="2025-06-28",
        ),
        current_balance=Period(
            instant="2026-06-27",
        ),
        prior_balance=Period(
            instant="2025-09-27",
        ),
    )

    summary = FinancialSummaryBuilder(normalized).build(periods)

    OUTPUT.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print("\nAPPLE FINANCIAL SUMMARY")
    print("=" * 76)

    income = summary["income_statement"]

    print(
        f'{"Metric":<22}'
        f'{"Current Q":>14}'
        f'{"Prior Q":>14}'
        f'{"Current YTD":>14}'
        f'{"Prior YTD":>14}'
    )

    for name in ("revenue", "operating_income", "net_income"):
        row = income[name]
        print(
            f"{name:<22}"
            f'{billions(row["current_quarter"]):>14}'
            f'{billions(row["prior_year_quarter"]):>14}'
            f'{billions(row["current_ytd"]):>14}'
            f'{billions(row["prior_year_ytd"]):>14}'
        )

    print("\nOPERATING CASH FLOW")
    cash_flow = summary["cash_flow"]
    print("Current YTD:", billions(cash_flow["current_ytd"]))
    print("Prior YTD:  ", billions(cash_flow["prior_year_ytd"]))

    print("\nBALANCE SHEET")
    balance = summary["balance_sheet"]

    for name in ("assets", "cash"):
        print(
            f"{name:<22}"
            f'{billions(balance[name]["current"]):>14}'
            f'{billions(balance[name]["prior"]):>14}'
        )

    print("\nRATIOS")
    ratios = summary["ratios"]

    for period_name in ("current_quarter", "current_ytd"):
        print(
            period_name,
            "operating margin:",
            percent(ratios[period_name]["operating_margin"]),
            "net margin:",
            percent(ratios[period_name]["net_margin"]),
        )

    print(
        "Quarterly revenue YoY growth:",
        percent(ratios["revenue_growth_quarter_yoy"]),
    )
    print(
        "YTD revenue YoY growth:",
        percent(ratios["revenue_growth_ytd_yoy"]),
    )

    print(f"\nFull JSON: {OUTPUT}")


if __name__ == "__main__":
    main()
