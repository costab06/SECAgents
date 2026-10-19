# SECAgents

Copyright 2026 Brian Costa

Licensed under the Apache License, Version 2.0.
See the LICENSE file for details.


**SECAgents v0.1.0** is a Python application that discovers SEC EDGAR filings, downloads the source documents, and extracts structured information using independent, event-driven agents built on [OpenAgentFabric](https://github.com/costab06/OpenAgentFabric).

This release is an **engineering demonstration of a multi-agent ingestion pipeline**, not an investment-recommendation service or a finished financial-research product.

## What it does

```text
SEC EDGAR
    |
    v
Watcher -- document.discovered --> Redis Streams
                                      |
                                      v
                                   Fetcher
                                      |
                             document.fetched
                                      |
                                      v
                                    Parser
                                      |
                             document.parsed
                                      |
                                      v
                              Local filing artifacts
```

- **Watcher:** Polls SEC EDGAR for recent filings for enabled companies, publishing discovered-filing events with a Redis-backed deduplication marker.
- **Fetcher:** Downloads filing documents and records checksums.
- **Parser:** Parses downloaded filings, extracts inline XBRL facts and related context, and writes structured artifacts.
- **OpenAgentFabric:** Supplies the shared agent runtime, event bus, correlation tracking, and consumer-group infrastructure.

The three agents communicate through a Redis stream. They can run as separate processes and are started independently.

## Demonstrated results

In a local four-company demonstration, the pipeline processed **two filings each** for Apple, Microsoft, Amazon, and JPMorgan Chase:

| Lifecycle event | Count |
| --- | ---: |
| `document.discovered` | 8 |
| `document.fetched` | 8 |
| `document.parsed` | 8 |

Eight `parsed.json` files were found, and both Fetcher and Parser consumer groups reported **zero pending messages and zero lag** after processing. The project test suite previously passed **49 tests**. Separately, an Apple financial-summary validation matched **18 of 18 selected facts** against SEC Company Facts for the tested filing.

These observations establish the result of the tested demonstration, not general guarantees about throughput, failure recovery, or financial-data accuracy for all issuers.

## Prerequisites

- Python **3.12 or newer**
- A running Redis server (the development configuration uses `localhost:6380`)
- Network access to SEC EDGAR
- An SEC-compliant `SEC_USER_AGENT` identifying your application and a contact email
- The **OpenAgentFabric** source repository, installed alongside SECAgents

### Repository layout

Clone both repositories under the same parent directory:

```text
Projects/
├── OpenAgentFabric/
└── SECAgents/
```

Example:

```bash
mkdir -p Projects
cd Projects
git clone https://github.com/costab06/OpenAgentFabric.git
git clone https://github.com/costab06/SECAgents.git
cd SECAgents
```

Both repositories must be accessible to the person installing the demonstration. The sibling directory layout is required by the installation instructions below.

## Installation

From the **SECAgents** project root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ../OpenAgentFabric
python -m pip install -e '.[dev]'
python -m pip check
```

The editable installation resolves the sibling repository dependency without changing Python imports or inserting paths into `PYTHONPATH`.

## Configuration

Edit `config/companies.yaml` to select the companies to monitor. The demonstration configuration includes:

| Ticker | CIK |
| --- | --- |
| AAPL | `0000320193` |
| MSFT | `0000789019` |
| AMZN | `0001018724` |
| JPM | `0000019617` |

Set `enabled: false` for a company you do not want to poll.

Set the SEC EDGAR identity in each terminal that runs the Watcher or Fetcher:

```bash
export SEC_USER_AGENT="SECAgents Your Name your-email@example.com"
```

Use a genuine application identifier and contact address. The provided startup scripts set these defaults consistently:

| Variable | Default | Used by |
| --- | --- | --- |
| `REDIS_URL` | `redis://localhost:6380/0` | All agents, reset |
| `OAF_STREAM` | `secagent.multicompany.v1` | All agents, reset |
| `SEC_MARKER_PREFIX` | `secagent:multicompany:v1` | Watcher, reset |
| `SEC_ARTIFACT_ROOT` | `data/filings` | Fetcher, Parser, reset |
| `SEC_USER_AGENT` | Required; no public default | Watcher, Fetcher |

The scripts accept environment overrides. The repository's `config/companies.yaml` is loaded relative to the working directory; the startup scripts change to the project root automatically.

## Running the pipeline

Start Redis first. Open **three terminals**, set `SEC_USER_AGENT` in the Watcher and Fetcher terminals, and launch the scripts in this order:

**Terminal 1 — Parser**

```bash
./start_parser.sh
```

**Terminal 2 — Fetcher**

```bash
./start_fetcher.sh
```

**Terminal 3 — Watcher**

```bash
./start_watcher.sh
```

The Watcher runs continuously, polling every **300 seconds** and inspecting up to **two recent qualifying filings per enabled company** on each cycle. Redis publication markers prevent repeat publication of the same filing within the configured marker namespace.

The equivalent Python entry points are `python -m secagent.agents.run_parser`, `python -m secagent.agents.run_fetcher`, and `python -m secagent.agents.run_watcher --continuous --interval 300 --limit 2`.

**Shutdown:** Stop the Watcher first, allow the Fetcher and Parser to finish, then stop those consumers.

## Checking the demonstration

Inspect Redis consumer groups:

```bash
redis-cli -p 6380 XINFO GROUPS secagent.multicompany.v1
```

Once processing finishes, look for `pending: 0` and `lag: 0` for the Fetcher and Parser groups. These counters show delivery progress; they do not independently prove that every filing was parsed successfully.

Count parsed artifacts by company:

```bash
for cik in 320193 789019 1018724 19617; do
    printf '%s: ' "$cik"
    find "data/filings/$cik" -name parsed.json 2>/dev/null | wc -l
done
```

For the demonstrated two-filings-per-company run, the expected output is two parsed files per CIK.

## Resetting the demo

**Stop all three agents before resetting.** From the repository root:

```bash
./scripts/reset_demo.sh
```

This deletes the dedicated demo Redis stream, its consumer groups, publication markers, and correlation records discoverable from `document.discovered` entries still present in that stream. It **preserves downloaded and parsed artifacts**.

For a full reset that also deletes the configured artifact directory:

```bash
./scripts/reset_demo.sh --all
```

The reset script asks for confirmation unless `--yes` is passed. **Warning:** `--all` recursively removes the configured `SEC_ARTIFACT_ROOT` (by default, `data/filings`), including previous validation artifacts. Keep research outputs you want to preserve outside that directory. Use only a dedicated demo stream and marker namespace; never reset a shared production stream. Correlations not represented by retained discovery events may remain until their TTL expires.

## Tests and validation

Run the unit tests:

```bash
python -m pytest -q
```

The repository also contains two targeted validation scripts:

```bash
python scripts/validate_apple_summary.py
python scripts/validate_sec_companyfacts.py
```

These scripts were used to construct an Apple financial summary and compare selected extracted facts against SEC Company Facts. They are validation utilities, not additional long-running agents. Their required inputs and expected outputs should be checked against the current script implementations before release.

## Project structure

```text
config/companies.yaml             Company watch list
src/secagent/agents/              Watcher, Fetcher, Parser, launch modules
src/secagent/clients/             EDGAR client
src/secagent/config/              Company configuration loader
src/secagent/parsing/             XBRL extraction and financial-fact utilities
start_*.sh                        Agent launch scripts
scripts/reset_demo.py             Demo reset logic
scripts/reset_demo.sh             Demo reset launcher
scripts/validate_*.py             Financial validation utilities
tests/                             Automated tests
```

## Scope and limitations

Version 0.1.0 focuses on ingestion and structured extraction. It does **not** yet provide:

- A historical financial database or a continuously updated cross-company financial model
- Comprehensive cross-company accounting normalization, especially for banks versus nonfinancial companies
- Automated anomaly detection, investment signals, or financial recommendations
- An interactive operational dashboard

The financial-fact and summary modules are included as early validation work; the independently checked Apple example should not be interpreted as comprehensive validation across all supported companies.

SEC EDGAR access is subject to SEC policies and rate limits. The data is provided by the SEC and issuers; this repository is an independent demonstration and is not affiliated with the SEC.

## Roadmap

A later release is planned to integrate **AgentVisor** for visibility into agent status, event flow, and processing outcomes. That integration and its technical publication are separate from v0.1.0.

## License

**To be decided before public release.** Add a `LICENSE` file and update this section with the chosen terms. No open-source license is implied by making a repository public.
