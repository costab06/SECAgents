"""Live repeated-execution checks for SECAgents.

Requires Redis and SEC_USER_AGENT. Does not mutate/delete existing Redis data.
Checks repeatable artifacts and per-execution completion-event counts; this is
NOT a simulated redelivery/atomic-commit test.
"""
import argparse
import asyncio
import hashlib
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

from redis.asyncio import Redis
from secagent.runtime import run_sec_cycle
from shared.eventbus.events import EventEnvelope, EventType


def artifact_path(ref):
    url = urlsplit(ref['uri'])
    if url.scheme != 'file' or url.netloc or url.query or url.fragment:
        raise ValueError(f"Not a local artifact URI: {ref['uri']}")
    path = Path(unquote(url.path))
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def snapshot(filing):
    output = {}
    for key in ('raw_artifact', 'parsed_artifact'):
        ref = filing[key]
        path = artifact_path(ref)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        declared = ref.get('sha256') or ref.get('checksum_sha256')
        if declared and str(declared).removeprefix('sha256:') != digest:
            raise AssertionError(f'{key}: declared SHA256 differs from actual bytes')
        output[key] = {'path': str(path), 'sha256': digest}
    return output


async def parsed_counts(redis, stream, correlations):
    counts = {c: 0 for c in correlations}
    cursor = '0-0'
    while True:
        entries = await redis.xread({stream: cursor}, count=200)
        if not entries:
            break
        for _, messages in entries:
            for message_id, fields in messages:
                cursor = message_id
                event = EventEnvelope.model_validate_json(fields['event'])
                cid = str(event.correlation_id)
                if cid in counts and event.event_type == EventType.DOCUMENT_PARSED:
                    counts[cid] += 1
    return counts


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cik', type=int, default=789019)
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--as-of', type=date.fromisoformat)
    parser.add_argument('--output', default='data/filings')
    parser.add_argument('--redis-url', default='redis://localhost:6380/0')
    parser.add_argument('--stream', default='secagent.integration')
    args = parser.parse_args()
    if not os.environ.get('SEC_USER_AGENT'):
        parser.error('Set SEC_USER_AGENT to your actual SEC contact identity')

    kwargs = dict(cik=args.cik, forms={'10-K', '10-Q'}, as_of=args.as_of,
                  limit=args.limit, timeout=args.timeout, output=args.output,
                  redis_url=args.redis_url, stream=args.stream)
    first = await run_sec_cycle(**kwargs)
    if not first['filings']:
        raise AssertionError('No filings discovered')
    before = {f['accession_number']: snapshot(f) for f in first['filings']}
    second = await run_sec_cycle(**kwargs)
    after = {f['accession_number']: snapshot(f) for f in second['filings']}
    assert before == after, f'Artifacts differ between runs: {before!r} vs {after!r}'
    assert first['request_id'] != second['request_id'], 'Execution request IDs were reused'
    c1 = {str(f['correlation_id']) for f in first['filings']}
    c2 = {str(f['correlation_id']) for f in second['filings']}
    assert c1.isdisjoint(c2), 'Correlation IDs reused across executions'

    redis = Redis.from_url(args.redis_url, decode_responses=True)
    try:
        counts = await parsed_counts(redis, args.stream, c1 | c2)
    finally:
        await redis.aclose()
    assert all(n == 1 for n in counts.values()), f'Unexpected completion event counts: {counts}'
    print(json.dumps({'status': 'PASS', 'filings': list(before),
                      'artifacts': before, 'parsed_events_per_correlation': counts}, indent=2))
    print('PASS: repeatable artifact bytes, unique execution correlations, one parsed event per execution')
    print('NOT TESTED: redelivery of the exact same event or downstream business-side-effect deduplication')


if __name__ == '__main__':
    asyncio.run(main())
