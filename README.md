# restock-agent

Crowdsourced Pokemon TCG restock reports for Cape Coral, Fort Myers, Naples, and
surrounding Southwest Florida stores. Reports come only from users of this bot or
from a clearly labeled, deterministic simulator.

**Current scope: milestones 0–3.** The prediction engine (`/predict`, backtesting)
and subscriber alerts are intentionally not implemented in this session. The
`predictions` table exists as a reserved cache for milestone 4.

## Architecture

```text
                    Discord slash commands
                              |
                              v
             bot/  parse input, autocomplete, format replies
                              |
                              v
       services/  validation, deduplication, business rules, DTOs
                              |
                              v
       repositories/  typed SQLAlchemy queries; never commit
                              |
                              v
       db/models.py -> PostgreSQL 16 (timestamptz, native enums)

scripts/seed_stores.py ---> repositories
scripts/simulate.py ------> simulator (pure generation) -> repositories
```

The bot has no SQL and no business logic. The only production write path for user
reports is `ReportService`. All timestamps are stored in UTC; conversion happens in
`bot/formatting.py` using the store's IANA timezone.

## What works

- PostgreSQL schema managed entirely by Alembic, including stores, sources,
  observations, and the future prediction cache.
- Idempotent store/source seeding from `data/stores_seed.csv`.
- `/report` with validation, hashed reporter IDs, and transaction-safe 30-minute
  deduplication.
- `/stores` and `/recent` with store autocomplete and New York time display.
- Deterministic simulator with weekly and random-daily planted patterns, reporting
  lag, missed restocks, false negatives, and source-scoped purge.
- Strict typing, linting, tests, structured JSON logs, and a GitHub Actions workflow.

## Quick start (8 commands)

```bash
git clone <your-repo-url> restock-agent && cd restock-agent
cp .env.example .env                  # fill in Discord values and salt
docker compose up -d --wait db
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python scripts/seed_stores.py
python -m restock.bot.main
```

On Windows PowerShell, use `Copy-Item .env.example .env`, `py -3.12 -m venv .venv`,
and `.venv\Scripts\Activate.ps1` before installing dependencies.

The Compose service creates both `restock` and `restock_test`. The test database is
only initialized on a fresh Compose volume.

## Discord setup

1. Create an application and bot in the Discord Developer Portal.
2. Put its token in `DISCORD_TOKEN` in `.env`.
3. Invite it to a private test server with the `bot` and `applications.commands`
   scopes.
4. Enable Developer Mode, copy the server ID, and set `GUILD_ID`.
5. Generate a salt for `REPORTER_HASH_SALT`:
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Commands are synced only to `GUILD_ID` in `setup_hook`, so changes appear
immediately. The bot needs no privileged message-content intent. Never commit
`.env`.

## Commands

| Command | Behavior |
| --- | --- |
| `/report store:<autocomplete> product:<choice> in_stock:<bool> [minutes_ago:0-2880] [note]` | Saves an ephemeral report and confirms privately. Nothing is posted publicly. |
| `/stores [retailer]` | Lists active stores and IDs. |
| `/recent store:<autocomplete> [product]` | Shows the latest 10 reports for a store, including source labels and local times. |

Store autocomplete matches substrings of store name or city. Reports older than 48
hours, future observations, notes over 280 characters, unknown stores, and duplicate
reports inside 30 minutes receive friendly ephemeral errors.

## Simulator

The simulator expects the six bundled `EXAMPLE ...` stores to be active. It refuses
to run if its planted store names are missing, so replacing the seed file with real
stores cannot silently mix synthetic rows into them.

```bash
python scripts/simulate.py --weeks 12 --seed 42
python scripts/simulate.py --weeks 12 --seed 42 --end-date 2026-10-26
python scripts/simulate.py --purge
```

Generation is deterministic for a fixed seed and end date. The default end date is
today in `America/New_York`, so pin `--end-date` when comparing runs. Every row has
`source=simulator` and a `SIMULATOR:` note, and `/recent` labels it.

| Store | Planted truth |
| --- | --- |
| EXAMPLE Target Cape Coral | Every Tuesday and Friday, 8–11am local |
| EXAMPLE Walmart Fort Myers | Random daily, 10% chance, 9am–8pm local |
| EXAMPLE Costco Naples | Every Thursday, 1–5pm local |
| EXAMPLE Best Buy Fort Myers | Every Saturday, 10am–1pm local |
| EXAMPLE Walgreens Cape Coral | Random daily, 5% chance |
| EXAMPLE Sams Club Naples | Random daily, 8% chance |

Noise includes 5–180 minute reporting lag, roughly 20% missed restocks, extra
observations, false-negative empty-shelf reports during restock windows, and
background empty-shelf reports. `--purge` deletes observations whose source is
`simulator`; it leaves user reports, stores, sources, and every other table intact.

## Tests and checks

```bash
python -m pytest -q
ruff check .
ruff format --check .
mypy src tests scripts
```

Tests use a real PostgreSQL database, not mocks. They read
`RESTOCK_TEST_DATABASE_URL` from the environment or `.env` and apply Alembic
migrations automatically. Service tests cover validation, hashing, deduplication,
recent-report queries, simulator persistence, and source-scoped purge. Bot behavior
is tested at the command parsing/formatting + service seam, never by connecting to
Discord.

CI runs Ruff, mypy, Alembic, and pytest against PostgreSQL 16.

## Decisions

- Deduplication is keyed by reporter hash, store, category, and `in_stock`, using
  `reported_at`. A transaction-scoped PostgreSQL advisory lock serializes the check
  so simultaneous identical submissions cannot both pass.
- Seed upserts use `(retailer, name, address)` as the natural key.
- All slash command responses are ephemeral to avoid publishing unverified reports.
- Display uses each store's timezone. All bundled stores use `America/New_York`.
- Reporter IDs are never stored or logged. Only a salted SHA-256 hash is stored.
- The simulator bypasses the Discord report service and de-duplication, but writes
  tagged source rows and uses the same database constraints.
- PostgreSQL native enums and `timestamptz` are used; no PostGIS. The haversine
  helper in `restock/geo.py` is ready for a future radius command.
- Commands are guild-synced, not globally synced, as requested for tonight.

## Limitations

- No prediction windows, backtest, `/predict`, subscriptions, or nightly worker yet.
- No scraping, LLM/agent layer, auto-purchasing, Facebook ingestion, or third-party
  Discord ingestion.
- Seed stores and coordinates are deliberately fake. Replace them before inviting
  real users.
- Simulator patterns are tied to the example store names and only cover six stores.
- Crowdsourced reports are unverified. Source trust weights are stored but are not
  yet applied to predictions.
- No moderation queue, per-user command cooldown, data-retention job, or store
  management command.
- This build environment had no Docker and no Discord token. The Compose path and
  live Discord login were not executed here; verification used local PostgreSQL 18,
  direct command-registration checks, and service-level tests. CI is configured for
  PostgreSQL 16 and will exercise the Compose-equivalent database path.
