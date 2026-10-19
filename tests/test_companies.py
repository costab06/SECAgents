
"""Tests for SEC company configuration loading."""

import pytest

from secagent.config.companies import load_companies


def test_load_enabled_companies(tmp_path):
    path = tmp_path / "companies.yaml"

    path.write_text(
        """
companies:
  - ticker: AAPL
    cik: "0000320193"
    name: Apple Inc.
    enabled: true

  - ticker: MSFT
    cik: "0000789019"
    name: Microsoft Corporation
    enabled: false
""",
        encoding="utf-8",
    )

    companies = load_companies(path)

    assert len(companies) == 1
    assert companies[0].ticker == "AAPL"
    assert companies[0].cik == 320193
    assert companies[0].name == "Apple Inc."
    assert companies[0].enabled is True


def test_duplicate_cik_rejected(tmp_path):
    path = tmp_path / "companies.yaml"

    path.write_text(
        """
companies:
  - ticker: AAPL
    cik: "0000320193"
    name: Apple Inc.

  - ticker: APPLE
    cik: 320193
    name: Apple Duplicate
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate CIK"):
        load_companies(path)


def test_invalid_enabled_flag_rejected(tmp_path):
    path = tmp_path / "companies.yaml"

    path.write_text(
        """
companies:
  - ticker: AAPL
    cik: "0000320193"
    name: Apple Inc.
    enabled: "yes"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid enabled"):
        load_companies(path)


def test_invalid_cik_rejected(tmp_path):
    path = tmp_path / "companies.yaml"

    path.write_text(
        """
companies:
  - ticker: AAPL
    cik: "not-a-cik"
    name: Apple Inc.
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Invalid CIK"):
        load_companies(path)
