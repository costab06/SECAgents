
"""Build auditable financial summaries from normalized XBRL facts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from secagent.parsing.financial_facts import (
    FactQuery,
    FinancialFactSelector,
)


CONCEPTS = {
    "revenue": (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:Revenues",
        "us-gaap:SalesRevenueNet",
    ),
    "net_income": ("us-gaap:NetIncomeLoss",),
    "operating_income": ("us-gaap:OperatingIncomeLoss",),
    "operating_cash_flow": (
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    ),
    "assets": ("us-gaap:Assets",),
    "cash": (
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
    ),
}


@dataclass(frozen=True)
class Period:
    start: str | None = None
    end: str | None = None
    instant: str | None = None

    def __post_init__(self):
        if self.instant:
            if self.start or self.end:
                raise ValueError(
                    "Instant period cannot have start/end dates"
                )
        elif not self.start or not self.end:
            raise ValueError(
                "Duration period requires start and end dates"
            )

    @property
    def period_type(self) -> str:
        return "instant" if self.instant else "duration"

    def as_dict(self) -> dict:
        return {
            "period_type": self.period_type,
            "start_date": self.start,
            "end_date": self.end,
            "instant": self.instant,
        }


@dataclass(frozen=True)
class SummaryPeriods:
    current_quarter: Period
    prior_year_quarter: Period
    current_ytd: Period
    prior_year_ytd: Period
    current_balance: Period
    prior_balance: Period


class FinancialSummaryBuilder:
    """Select financial facts and calculate derived metrics."""

    def __init__(self, normalized_xbrl: dict[str, Any]):
        self.selector = FinancialFactSelector(normalized_xbrl)

    def _metric(
        self,
        metric: str,
        period: Period,
    ) -> dict:
        for concept in CONCEPTS[metric]:
            matches = self.selector.select(
                FactQuery(
                    concept=concept,
                    period_type=period.period_type,
                    start_date=period.start,
                    end_date=period.end,
                    instant=period.instant,
                    dimensionless_only=True,
                )
            )

            # Only USD facts are suitable for these metrics.
            # Resolve unit references using the extracted unit
            # definitions rather than assuming the ID is "usd".
            usd_matches = []

            for fact in matches:
                unit_ref = fact.get("unit_ref")
                unit = self.selector.units.get(unit_ref, {})
                measures = unit.get("measures", [])

                if measures == ["iso4217:USD"]:
                    usd_matches.append(fact)

            if not usd_matches:
                continue

            values = {
                fact["normalized_value"]
                for fact in usd_matches
            }

            # Distinct representations of the same Decimal are
            # equivalent; distinct amounts are ambiguous.
            decimal_values = {
                Decimal(value) for value in values
            }

            if len(decimal_values) != 1:
                return {
                    "status": "ambiguous",
                    "value": None,
                    "concept": concept,
                    "period": period.as_dict(),
                    "candidate_count": len(usd_matches),
                }

            value = next(iter(decimal_values))

            return {
                "status": "selected",
                "value": format(value, "f"),
                "concept": concept,
                "period": period.as_dict(),
                "candidate_count": len(usd_matches),
                "context_refs": sorted({
                    str(fact.get("context_ref"))
                    for fact in usd_matches
                }),
            }

        return {
            "status": "missing",
            "value": None,
            "concept": None,
            "period": period.as_dict(),
            "candidate_count": 0,
        }

    @staticmethod
    def _ratio(
        numerator: dict,
        denominator: dict,
    ) -> dict:
        if (
            numerator["status"] != "selected"
            or denominator["status"] != "selected"
        ):
            return {
                "status": "unavailable",
                "value": None,
            }

        top = Decimal(numerator["value"])
        bottom = Decimal(denominator["value"])

        if bottom == 0:
            return {
                "status": "division_by_zero",
                "value": None,
            }

        value = top / bottom * Decimal(100)

        return {
            "status": "calculated",
            "value": format(value.quantize(Decimal("0.01")), "f"),
            "unit": "percent",
        }

    @classmethod
    def _growth(
        cls,
        current: dict,
        prior: dict,
    ) -> dict:
        if (
            current["status"] != "selected"
            or prior["status"] != "selected"
        ):
            return {
                "status": "unavailable",
                "value": None,
            }

        current_value = Decimal(current["value"])
        prior_value = Decimal(prior["value"])

        if prior_value <= 0:
            return {
                "status": "invalid_comparison_base",
                "value": None,
            }

        change = {
            "status": "selected",
            "value": str(current_value - prior_value),
        }
        base = {
            "status": "selected",
            "value": str(prior_value),
        }

        return cls._ratio(change, base)

    def build(
        self,
        periods: SummaryPeriods,
    ) -> dict:
        income_metrics = (
            "revenue",
            "net_income",
            "operating_income",
        )

        income = {}

        for metric in income_metrics:
            income[metric] = {
                "current_quarter": self._metric(
                    metric, periods.current_quarter
                ),
                "prior_year_quarter": self._metric(
                    metric, periods.prior_year_quarter
                ),
                "current_ytd": self._metric(
                    metric, periods.current_ytd
                ),
                "prior_year_ytd": self._metric(
                    metric, periods.prior_year_ytd
                ),
            }

        cash_flow = {
            "current_ytd": self._metric(
                "operating_cash_flow", periods.current_ytd
            ),
            "prior_year_ytd": self._metric(
                "operating_cash_flow", periods.prior_year_ytd
            ),
        }

        balance = {}

        for metric in ("assets", "cash"):
            balance[metric] = {
                "current": self._metric(
                    metric, periods.current_balance
                ),
                "prior": self._metric(
                    metric, periods.prior_balance
                ),
            }

        ratios = {}

        for label in (
            "current_quarter",
            "prior_year_quarter",
            "current_ytd",
            "prior_year_ytd",
        ):
            ratios[label] = {
                "operating_margin": self._ratio(
                    income["operating_income"][label],
                    income["revenue"][label],
                ),
                "net_margin": self._ratio(
                    income["net_income"][label],
                    income["revenue"][label],
                ),
            }

        ratios["revenue_growth_quarter_yoy"] = self._growth(
            income["revenue"]["current_quarter"],
            income["revenue"]["prior_year_quarter"],
        )
        ratios["revenue_growth_ytd_yoy"] = self._growth(
            income["revenue"]["current_ytd"],
            income["revenue"]["prior_year_ytd"],
        )

        return {
            "schema_version": "1.0",
            "income_statement": income,
            "cash_flow": cash_flow,
            "balance_sheet": balance,
            "ratios": ratios,
        }
