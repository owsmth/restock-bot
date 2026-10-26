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
- Optional anonymous public restock feed for `/report` when a channel is configured.
- Per-reporter hourly rate limiting plus Manage Server admin commands and `/help`.
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
6. Optional: set `LOCAL_RESTOCK_CHANNEL_ID` to the channel that should receive the
   anonymous restock feed. Give the bot View Channel, Send Messages, and Embed Links
   there. Leave it unset to disable the feed. Set `REPORT_RATE_LIMIT_PER_HOUR` if the
   default of 10 reports per reporter per hour is not suitable.

Commands are synced only to `GUILD_ID` in `setup_hook`, so changes appear
immediately. The bot needs no privileged message-content intent. Never commit
`.env`.

## Commands

| Command | Behavior |
| --- | --- |
| `/report store:<autocomplete> product:<choice> in_stock:<bool> [minutes_ago:0-2880] [note]` | Saves an ephemeral report and confirms privately. If the feed is enabled, also posts an anonymous update. |
| `/stores [retailer]` | Lists active stores and IDs. |
| `/recent store:<autocomplete> [product]` | Shows the latest 10 reports for a store, including source labels and local times. |
| `/help` | Ephemeral explanation of `/report`, `/stores`, and `/recent`. |
| `/admin_delete_report id` | Deletes one report. Manage Server by default; ephemeral. |
| `/admin_set_store_active store active` | Activates or deactivates a store, including inactive stores in autocomplete. Manage Server by default; ephemeral. |

Store autocomplete matches case-insensitive tokens across retailer, name, city, and
address, ranks prefix matches first, and shows at most 25 choices. Reports older than
48 hours, future observations, notes over 280 characters, unknown stores, duplicate
reports inside 30 minutes, and reporters over their hourly limit receive friendly
ephemeral errors.

## Rate limits and admin commands

`REPORT_RATE_LIMIT_PER_HOUR` defaults to `10`. The limit is a rolling one-hour window
per salted reporter hash and is enforced inside the report service under a PostgreSQL
advisory lock, so changing the env var requires a bot restart.

The two `/admin_...` commands are registered with
`default_member_permissions=Manage Server`, respond ephemerally, and log an
`admin_action` event with the action, outcome, and database IDs. Admin logs never
include the acting Discord user ID, guild ID, channel ID, or reporter hash.

## Public feed (optional)

When `LOCAL_RESTOCK_CHANNEL_ID` is set, every saved report posts a compact embed to
that channel with the store and city, product, in-stock/out-of-stock styling, and the
observed time as a Discord relative timestamp. The embed contains no reporter name,
hash, or mention, and the bot sends it with `allowed_mentions=none`.

If the channel is missing, permissions are wrong, or Discord rejects the post, the
bot logs a warning and returns the normal private confirmation; the report is never
rolled back. When a post succeeds, the private confirmation says it was shared
anonymously instead of saying nothing was posted publicly.

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

## Store candidate export (optional)

```bash
python scripts/fetch_osm_stores.py
```

This makes one Overpass API request for the ten supported brands inside a bounding
box covering Cape Coral, Fort Myers, Bonita Springs, and Naples. It writes
`data/stores_osm_candidates.csv` in the seed CSV format and never connects to the
database. The command refuses to overwrite an existing file unless `--force` is
passed.

Review and edit every row before using it. Rows with no OSM street or city are kept
so they are visible for review, but have blank fields until you fill them in. Then
merge the reviewed rows into `data/stores_seed.csv` and run the normal seed command.
`scripts/seed_stores.py` rejects duplicate `(retailer, name, address)` rows and
prints created/updated totals.

Store candidate data comes from OpenStreetMap, © OpenStreetMap contributors,
available under the [Open Database License](https://www.openstreetmap.org/copyright).
The export is deliberately manual: no OSM data is inserted without review.

## Cleanup example data

After the real store CSV is reviewed and seeded, remove the six demonstration
stores and every simulator row:

```bash
python scripts/remove_example_data.py --yes
```

Without `--yes` the command refuses to change anything and exits. It deletes
observations first, then stores, and prints store/observation counts before and
after. All stores whose names start with `EXAMPLE` are removed, along with every
observation at those stores and every observation from the `simulator` source.
Sources, real stores, and real user reports are left intact.

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
rate limiting, recent-report queries, admin deletion/store activation, simulator
persistence, and source-scoped purge. Bot behavior is tested at the command
parsing/formatting + service seam, never by connecting to Discord.

CI runs Ruff, mypy, Alembic, and pytest against PostgreSQL 16.

## Decisions

- Deduplication is keyed by reporter hash, store, category, and `in_stock`, using
  `reported_at`. A transaction-scoped PostgreSQL advisory lock serializes the check
  so simultaneous identical submissions cannot both pass.
- Seed upserts use `(retailer, name, address)` as the natural key. Duplicate rows
  are rejected before the database is opened, with line numbers in the error.
- OSM store candidates are a one-time, single-request, read-only export for manual
  review. The script never seeds the database, and OSM data is attributed under ODbL.
- Example data cleanup is explicit (`--yes`), removes observations before stores,
  and also removes all `simulator`-source observations. It never removes sources or
  real user reports.
- Store autocomplete loads the active store set (expected around 100) and ranks in
  Python because matching spans the retailer, name, city, and address and prefix
  matches must sort first. It returns at most 25 choices with case-insensitive
  token matching and truncates each label to Discord's 100-character limit.
- The public feed is opt-in through `LOCAL_RESTOCK_CHANNEL_ID`. The report service
  returns the announcement data (including store city), while a bot-layer notifier
  builds and posts the embed. Posting failures log a warning and return `False`; they
  never roll back the saved report. The embed has no reporter identity, uses
  `allowed_mentions=none`, and renders observed time as a relative timestamp.
- Rate limiting is a rolling hour per `reporter_hash`, defaulting to 10 and configurable
  with `REPORT_RATE_LIMIT_PER_HOUR`. A reporter-level advisory lock counts accepted
  Discord reports before insert, so concurrent submissions cannot bypass it.
- Admin commands use `default_member_permissions=Manage Server`, keep all responses
  ephemeral, and write structured action logs without Discord user, guild, or channel
  IDs or reporter hashes.
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
- Simulator patterns are tied to the example store names and only cover six stores.
- Crowdsourced reports are unverified. Source trust weights are stored but are not
  yet applied to predictions.
- No moderation queue, data-retention job, or scheduled jobs yet.
- Admin commands rely on Discord's default command permissions; a server administrator
  can override the default permission in Discord's integration settings.
- The bundled seed CSV is still deliberately fake until the reviewed OSM candidates
  replace it. No real store data was invented or committed.
- GitHub Actions has not run yet. Optionally configured feed/rate-limit/admin commands
  are tested locally but have not been exercised live until the bot is restarted.
