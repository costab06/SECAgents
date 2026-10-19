
from secagent.parsing.financial_facts import (
    FactQuery,
    FinancialFactSelector,
)


def make_fact(
    concept,
    value,
    *,
    start=None,
    end=None,
    instant=None,
    dimensions=None,
    unit="usd",
):
    return {
        "name": concept,
        "value": value,
        "normalized_value": value,
        "normalization_status": "normalized",
        "unit_ref": unit,
        "resolved_context": {
            "period_type": (
                "instant" if instant else "duration"
            ),
            "start_date": start,
            "end_date": end,
            "instant": instant,
            "dimensions": dimensions or [],
        },
    }


def make_selector():
    return FinancialFactSelector({
        "units": {},
        "facts": [
            make_fact(
                "us-gaap:Revenues",
                "100000000",
                start="2026-04-01",
                end="2026-06-30",
            ),
            make_fact(
                "us-gaap:Revenues",
                "290000000",
                start="2026-01-01",
                end="2026-06-30",
            ),
            make_fact(
                "us-gaap:Revenues",
                "85000000",
                start="2025-04-01",
                end="2025-06-30",
            ),
            make_fact(
                "us-gaap:Revenues",
                "25000000",
                start="2026-04-01",
                end="2026-06-30",
                dimensions=[
                    {
                        "dimension": "segment",
                        "member": "services",
                    }
                ],
            ),
            make_fact(
                "us-gaap:Assets",
                "500000000",
                instant="2026-06-30",
            ),
        ],
    })


def test_select_quarterly_revenue():
    selector = make_selector()

    matches = selector.quarterly(
        "us-gaap:Revenues",
        "2026-04-01",
        "2026-06-30",
    )

    assert len(matches) == 1
    assert matches[0]["normalized_value"] == "100000000"


def test_excludes_year_to_date():
    selector = make_selector()

    matches = selector.quarterly(
        "us-gaap:Revenues",
        "2026-04-01",
        "2026-06-30",
    )

    assert all(
        fact["resolved_context"]["start_date"]
        == "2026-04-01"
        for fact in matches
    )


def test_select_instant_assets():
    selector = make_selector()

    matches = selector.instant(
        "us-gaap:Assets",
        "2026-06-30",
    )

    assert len(matches) == 1
    assert matches[0]["normalized_value"] == "500000000"


def test_dimensionless_excludes_segments():
    selector = make_selector()

    matches = selector.select(
        FactQuery(
            concept="us-gaap:Revenues",
            start_date="2026-04-01",
            end_date="2026-06-30",
        )
    )

    assert len(matches) == 1


def test_can_include_segments():
    selector = make_selector()

    matches = selector.select(
        FactQuery(
            concept="us-gaap:Revenues",
            start_date="2026-04-01",
            end_date="2026-06-30",
            dimensionless_only=False,
        )
    )

    assert len(matches) == 2


def test_available_periods():
    selector = make_selector()

    periods = selector.available_periods(
        "us-gaap:Revenues"
    )

    assert len(periods) == 3
