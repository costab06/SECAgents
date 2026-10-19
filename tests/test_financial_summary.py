
from secagent.parsing.financial_summary import (
    FinancialSummaryBuilder,
    Period,
    SummaryPeriods,
)


def make_fact(concept, value, period, unit_ref="u1"):
    return {
        "name": concept,
        "normalized_value": str(value),
        "normalization_status": "normalized",
        "unit_ref": unit_ref,
        "context_ref": f"c-{concept}-{period.start}-{period.end}-{period.instant}",
        "resolved_context": {
            **period.as_dict(),
            "dimensions": [],
        },
    }


def sample_periods():
    return SummaryPeriods(
        current_quarter=Period(
            start="2026-04-01", end="2026-06-30"
        ),
        prior_year_quarter=Period(
            start="2025-04-01", end="2025-06-30"
        ),
        current_ytd=Period(
            start="2026-01-01", end="2026-06-30"
        ),
        prior_year_ytd=Period(
            start="2025-01-01", end="2025-06-30"
        ),
        current_balance=Period(instant="2026-06-30"),
        prior_balance=Period(instant="2025-06-30"),
    )


def sample_data():
    periods = sample_periods()

    revenue = (
        "us-gaap:"
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    )

    facts = [
        make_fact(revenue, "120000000", periods.current_quarter),
        make_fact(revenue, "100000000", periods.prior_year_quarter),
        make_fact(revenue, "350000000", periods.current_ytd),
        make_fact(revenue, "300000000", periods.prior_year_ytd),
        make_fact(
            "us-gaap:NetIncomeLoss",
            "30000000",
            periods.current_quarter,
        ),
        make_fact(
            "us-gaap:OperatingIncomeLoss",
            "36000000",
            periods.current_quarter,
        ),
        make_fact(
            "us-gaap:Assets",
            "900000000",
            periods.current_balance,
        ),
        make_fact(
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            "100000000",
            periods.current_balance,
        ),
        make_fact(
            "us-gaap:NetCashProvidedByUsedInOperatingActivities",
            "80000000",
            periods.current_ytd,
        ),
    ]

    return {
        "facts": facts,
        "units": {
            "u1": {"measures": ["iso4217:USD"]},
        },
    }


def test_revenue_growth():
    result = FinancialSummaryBuilder(
        sample_data()
    ).build(sample_periods())

    growth = result["ratios"]["revenue_growth_quarter_yoy"]

    assert growth["status"] == "calculated"
    assert growth["value"] == "20.00"


def test_operating_and_net_margins():
    result = FinancialSummaryBuilder(
        sample_data()
    ).build(sample_periods())

    margins = result["ratios"]["current_quarter"]

    assert margins["operating_margin"]["value"] == "30.00"
    assert margins["net_margin"]["value"] == "25.00"


def test_balance_sheet_instant():
    result = FinancialSummaryBuilder(
        sample_data()
    ).build(sample_periods())

    assets = result["balance_sheet"]["assets"]["current"]

    assert assets["status"] == "selected"
    assert assets["value"] == "900000000"


def test_cash_flow_ytd():
    result = FinancialSummaryBuilder(
        sample_data()
    ).build(sample_periods())

    cash_flow = result["cash_flow"]["current_ytd"]

    assert cash_flow["value"] == "80000000"


def test_missing_metric_is_explicit():
    result = FinancialSummaryBuilder(
        sample_data()
    ).build(sample_periods())

    missing = result["income_statement"][
        "net_income"
    ]["prior_year_quarter"]

    assert missing["status"] == "missing"
    assert missing["value"] is None


def test_ambiguous_values_are_not_silently_selected():
    data = sample_data()
    periods = sample_periods()

    data["facts"].append(
        make_fact(
            "us-gaap:"
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "121000000",
            periods.current_quarter,
        )
    )

    result = FinancialSummaryBuilder(data).build(periods)

    revenue = result["income_statement"][
        "revenue"
    ]["current_quarter"]

    assert revenue["status"] == "ambiguous"
    assert revenue["value"] is None

    assert result["ratios"][
        "revenue_growth_quarter_yoy"
    ]["status"] == "unavailable"


def test_non_usd_units_are_excluded():
    data = sample_data()
    data["units"]["u1"] = {
        "measures": ["xbrli:shares"]
    }

    result = FinancialSummaryBuilder(
        data
    ).build(sample_periods())

    assert result["income_statement"][
        "revenue"
    ]["current_quarter"]["status"] == "missing"
