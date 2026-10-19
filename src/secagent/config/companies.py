
"""Load and validate SEC company monitoring configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Company:
    ticker: str
    cik: int
    name: str
    enabled: bool = True


def load_companies(path: str | Path) -> list[Company]:
    """Return enabled companies from a YAML configuration file."""
    path = Path(path)

    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if not isinstance(config, dict):
        raise ValueError("Company configuration must be a mapping")

    entries = config.get("companies")

    if not isinstance(entries, list):
        raise ValueError("'companies' must be a list")

    companies = []
    seen_ciks = set()
    seen_tickers = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Company {index} must be a mapping")

        ticker = entry.get("ticker")
        name = entry.get("name")
        raw_cik = entry.get("cik")
        enabled = entry.get("enabled", True)

        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError(f"Invalid ticker at index {index}")

        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Invalid company name at index {index}")

        if isinstance(raw_cik, bool) or not (
            isinstance(raw_cik, int)
            or (isinstance(raw_cik, str) and raw_cik.isdigit())
        ):
            raise ValueError(f"Invalid CIK at index {index}")

        cik = int(raw_cik)

        if cik <= 0:
            raise ValueError(f"CIK must be positive at index {index}")

        if not isinstance(enabled, bool):
            raise ValueError(f"Invalid enabled flag at index {index}")

        ticker = ticker.strip().upper()
        name = name.strip()

        if cik in seen_ciks:
            raise ValueError(f"Duplicate CIK: {cik}")

        if ticker in seen_tickers:
            raise ValueError(f"Duplicate ticker: {ticker}")

        seen_ciks.add(cik)
        seen_tickers.add(ticker)

        if enabled:
            companies.append(
                Company(
                    ticker=ticker,
                    cik=cik,
                    name=name,
                    enabled=True,
                )
            )

    return companies
