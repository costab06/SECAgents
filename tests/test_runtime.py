"""Focused tests for secagent.runtime; no live SEC or Redis required."""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from secagent import runtime
from secagent.clients.edgar import Filing


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs,error", [
    ({"cik": 0}, "cik"),
    ({"cik": True}, "cik"),
    ({"cik": 789019, "limit": 0}, "limit"),
    ({"cik": 789019, "timeout": 0}, "timeout"),
    ({"cik": 789019, "forms": set()}, "forms"),
    ({"cik": 789019, "as_of": "2024-01-01"}, "as_of"),
    ({"cik": 789019, "stream": ""}, "stream"),
])
async def test_invalid_inputs_fail_before_network(kwargs, error):
    with pytest.raises((ValueError, TypeError), match=error):
        await runtime.run_sec_cycle(user_agent="Test Agent contact@example.org", **kwargs)


@pytest.mark.asyncio
async def test_identity_required(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        await runtime.run_sec_cycle(cik=789019)


@pytest.mark.asyncio
async def test_empty_discovery_filters_as_of_and_cleans_up(monkeypatch, tmp_path):
    filing = Filing(
        cik=789019,
        company_name="Microsoft Corp",
        form="10-K",
        accession_number="0000789019-25-000001",
        filing_date=date(2025, 8, 1),
        primary_document="report.htm",
    )
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    redis.aclose = AsyncMock()
    redis_cls = MagicMock()
    redis_cls.from_url.return_value = redis
    monkeypatch.setattr(runtime, "Redis", redis_cls)

    bus = MagicMock()
    bus.close = AsyncMock()
    monkeypatch.setattr(runtime, "RedisEventBus", MagicMock(return_value=bus))

    edgar = MagicMock()
    edgar.get_recent_filings = AsyncMock(return_value=[filing])
    edgar_context = MagicMock()
    edgar_context.__aenter__ = AsyncMock(return_value=edgar)
    edgar_context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(runtime, "EdgarClient", MagicMock(return_value=edgar_context))

    result = await runtime.run_sec_cycle(
        cik=789019,
        as_of=date(2024, 12, 31),
        output=tmp_path,
        user_agent="Test Agent contact@example.org",
    )

    assert result["filings"] == []
    assert result["as_of"] == "2024-12-31"
    edgar.get_recent_filings.assert_awaited_once_with(
        cik=789019, forms={"10-K", "10-Q"}, limit=None
    )
    redis.aclose.assert_awaited_once()
    bus.close.assert_awaited_once()
