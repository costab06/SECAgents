
"""Compare a generated financial summary with SEC Company Facts."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import httpx


CIK = "0000320193"
ACCESSION = "0000320193-26-000020"

ROOT = Path("data/filings/320193") / ACCESSION
SUMMARY_PATH = ROOT / "financial-summary.json"
REPORT_PATH = ROOT / "sec-validation.json"

SEC_URL = (
    f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
)


def iter_metrics(summary: dict):
    for metric, periods in summary["income_statement"].items():
        for label, fact in periods.items():
            yield f"income_statement.{metric}.{label}", fact

    for label, fact in summary["cash_flow"].items():
        yield f"cash_flow.{label}", fact

    for metric, periods in summary["balance_sheet"].items():
        for label, fact in periods.items():
            yield f"balance_sheet.{metric}.{label}", fact


def validate_fact(
    name: str,
    selected: dict,
    companyfacts: dict,
) -> dict:
    result = {
        "metric": name,
        "status": None,
        "selected_value": selected.get("value"),
        "concept": selected.get("concept"),
        "period": selected.get("period"),
        "sec_values": [],
    }

    if selected.get("status") != "selected":
        result["status"] = "not_selected"
        return result

    concept = selected["concept"]

    if ":" not in concept:
        result["status"] = "invalid_concept"
        return result

    namespace, tag = concept.split(":", 1)

    concept_data = (
        companyfacts.get("facts", {})
        .get(namespace, {})
        .get(tag)
    )

    if concept_data is None:
        result["status"] = "concept_not_found"
        return result

    usd_records = concept_data.get("units", {}).get("USD", [])

    period = selected["period"]

    candidates = []

    for record in usd_records:
        if record.get("accn") != ACCESSION:
            continue

        if period["period_type"] == "instant":
            if record.get("start") is not None:
                continue
            if record.get("end") != period["instant"]:
                continue
        else:
            if record.get("start") != period["start_date"]:
                continue
            if record.get("end") != period["end_date"]:
                continue

        candidates.append(record)

    if not candidates:
        result["status"] = "period_not_found"
        return result

    sec_values = sorted({
        Decimal(str(record["val"]))
        for record in candidates
    })

    result["sec_values"] = [
        format(value, "f") for value in sec_values
    ]

    if len(sec_values) > 1:
        result["status"] = "sec_ambiguous"
        return result

    selected_value = Decimal(selected["value"])

    result["status"] = (
        "match"
        if selected_value == sec_values[0]
        else "mismatch"
    )

    return result


def main():
    summary = json.loads(
        SUMMARY_PATH.read_text(encoding="utf-8")
    )

    user_agent = os.environ.get("SEC_USER_AGENT")

    if not user_agent:
        raise RuntimeError(
            "Set SEC_USER_AGENT to your application name "
            "and contact email before requesting SEC data."
        )

    with httpx.Client(
        timeout=60.0,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
    ) as client:
        response = client.get(SEC_URL)
        response.raise_for_status()
        companyfacts = response.json()

    results = [
        validate_fact(name, fact, companyfacts)
        for name, fact in iter_metrics(summary)
    ]

    counts = {}

    for result in results:
        status = result["status"]
        counts[status] = counts.get(status, 0) + 1

    report = {
        "cik": CIK,
        "accession": ACCESSION,
        "counts": counts,
        "results": results,
    }

    REPORT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nSEC COMPANY FACTS VALIDATION")
    print("=" * 76)

    for result in results:
        print(
            f'{result["status"]:<20}'
            f'{result["metric"]:<48}'
            f'{result["selected_value"]}'
        )

        if result["status"] in ("mismatch", "sec_ambiguous"):
            print("  SEC values:", result["sec_values"])

    print("\nCOUNTS:", counts)
    print("Report:", REPORT_PATH)

    if counts.get("mismatch", 0):
        raise SystemExit(1)

    if counts.get("sec_ambiguous", 0):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
