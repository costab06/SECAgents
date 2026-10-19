"""Select normalized XBRL financial facts by concept and context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable


@dataclass(frozen=True)
class FactQuery:
    concept: str
    period_type: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    instant: str | None = None
    dimensionless_only: bool = True
    unit: str | None = None


class FinancialFactSelector:
    """Query normalized XBRL facts without discarding context."""

    def __init__(self, normalized_xbrl: dict[str, Any]):
        self.facts = normalized_xbrl.get("facts", [])
        self.units = normalized_xbrl.get("units", {})

    def select(self, query: FactQuery) -> list[dict]:
        matches = []

        for fact in self.facts:
            if fact.get("name") != query.concept:
                continue

            if fact.get("normalization_status") != "normalized":
                continue

            context = fact.get("resolved_context")

            if not context:
                continue

            if (
                    query.period_type is not None
                    and context.get("period_type") != query.period_type
            ):
                continue

            if (
                    query.start_date is not None
                    and context.get("start_date") != query.start_date
            ):
                continue

            if (
                    query.end_date is not None
                    and context.get("end_date") != query.end_date
            ):
                continue

            if (
                    query.instant is not None
                    and context.get("instant") != query.instant
            ):
                continue

            if (
                    query.dimensionless_only
                    and context.get("dimensions")
            ):
                continue

            if (
                    query.unit is not None
                    and fact.get("unit_ref") != query.unit
            ):
                continue

            matches.append(fact)

        return matches

    def quarterly(
            self,
            concept: str,
            start: str,
            end: str,
    ) -> list[dict]:
        """Select an explicitly specified reporting duration."""
        return self.select(
            FactQuery(
                concept=concept,
                period_type="duration",
                start_date=start,
                end_date=end,
            )
        )

    def instant(
            self,
            concept: str,
            as_of: str,
    ) -> list[dict]:
        """Select balance-sheet facts for an exact reporting date."""
        return self.select(
            FactQuery(
                concept=concept,
                period_type="instant",
                instant=as_of,
            )
        )

    def available_periods(
            self,
            concept: str,
    ) -> list[dict]:
        """List distinct periods available for a financial concept."""
        periods = {}

        for fact in self.select(FactQuery(concept=concept)):
            context = fact["resolved_context"]

            key = (
                context.get("period_type"),
                context.get("start_date"),
                context.get("end_date"),
                context.get("instant"),
            )

            periods[key] = {
                "period_type": key[0],
                "start_date": key[1],
                "end_date": key[2],
                "instant": key[3],
            }

        return list(periods.values())
