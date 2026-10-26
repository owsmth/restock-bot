# restock-agent

Crowdsourced Pokemon TCG restock reports for Cape Coral, Fort Myers, Naples, and
surrounding Southwest Florida stores. Reports come only from users of this bot or
from a clearly labeled simulator.

This repository is being delivered in milestones. Current scope: foundation, data
layer, Discord commands, and simulator. Prediction and alerts are intentionally out
of scope for this session.

## Architecture

```text
Discord slash commands
        |
        v
bot/ (parse + format only)
        |
        v
services/ (validation, business rules)
        |
        v
repositories/ --> SQLAlchemy models --> PostgreSQL 16
```

Timestamps are stored in UTC (`timestamptz`). Display conversion happens in the bot
formatting layer using each store's IANA timezone.

## Quick start

```bash
cp .env.example .env                 # then fill in DISCORD_TOKEN, GUILD_ID, salt
docker compose up -d db
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python scripts/seed_stores.py
python -m restock.bot.main
```

On Windows PowerShell, create and activate the environment with
`.venv\Scripts\Activate.ps1`.

## Decisions

- De-duplication compares submissions by `reported_at`; observed time is kept for
  analytics.
- Seed-upserts use `(retailer, name, address)` as a natural key.
- Slash command responses are ephemeral to avoid publishing unverified reports.
- Displayed times use the store's IANA timezone, which is `America/New_York` for all
  bundled examples.
- The simulator writes through the repository as a trusted source, so it bypasses
  Discord de-duplication while remaining purgeable by source.
- Docker isn't available in every development environment. Tests still require a
  real PostgreSQL database via `RESTOCK_TEST_DATABASE_URL`.

## Limitations

- No prediction engine, alerts, scraping, auto-purchasing, or third-party ingestion.
- Seed stores are fake examples and must be replaced before real use.
- The simulator is tied to the names of the bundled example stores.
- Crowdsourced reports are unverified and may be inaccurate or stale.
