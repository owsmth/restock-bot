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
scripts/import_observations_csv.py -> CSV validation -> repositories
```

The bot has no SQL and no business logic. The only production write path for user
reports is `ReportService`. All timestamps are stored in UTC; conversion happens in
`bot/formatting.py` using the store's IANA timezone.

## What works

- PostgreSQL schema managed entirely by Alembic, including stores, sources,
  observations, and the future prediction cache.
- Idempotent store/source seeding from `data/stores_seed.csv` (106 Southwest Florida
  stores) plus a separate example set for the simulator.
- `/report` with store outcomes, optional product/quantity/text fields, hashed
  reporter IDs, and transaction-safe 30-minute deduplication per store and outcome.
- `/stores` and `/recent` with store autocomplete, outcome labels, and New York time
  display.
- Optional anonymous public restock feed for `/report` when a channel is configured.
- Per-reporter hourly rate limiting plus Manage Server admin commands and `/help`.
- A `ReportParser` seam and confirmation view for future free-text parsing; no model
  or external API is bundled yet.
- An operator-reviewed CSV importer for historical observations with dry-run,
  store-hint mapping validation, and imported-row isolation.
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
   default of 10 reports per reporter per hour is not suitable. Free-text reports
   stay disabled unless `REPORT_PARSER_ENABLED=true` and a parser is injected.

Commands are synced only to `GUILD_ID` in `setup_hook`, so changes appear
immediately. The bot needs no privileged message-content intent. Never commit
`.env`.

## Commands

| Command | Behavior |
| --- | --- |
| `/report [store] [outcome:4 choices] [products] [quantity] [text]` | All options are optional. Store and outcome save directly as a dropdown report. Text by itself uses the free-text parser, when enabled, and shows an ephemeral Confirm/Cancel view. If the feed is enabled, saved reports are posted anonymously. |
| `/stores [retailer]` | Lists active stores and IDs. |
| `/recent store:<autocomplete> [product]` | Shows the latest 10 reports for a store with `DROP`, `IN STOCK`, `SOLD OUT`, or `NOTHING` labels, source labels, and local times. |
| `/help` | Ephemeral explanation of `/report`, `/stores`, and `/recent`. |
| `/admin_delete_report id` | Deletes one report. Manage Server by default; ephemeral. |
| `/admin_set_store_active store active` | Activates or deactivates a store, including inactive stores in autocomplete. Manage Server by default; ephemeral. |

Store autocomplete matches case-insensitive tokens across retailer, name, city, and
address, ranks prefix matches first, and shows at most 25 choices. Unknown stores,
duplicate store/outcome reports inside 30 minutes, notes over 280 characters, quantity
notes over 200 characters, raw text over 2,000 characters, and reporters over their
hourly limit receive friendly ephemeral errors. The free-text path is disabled unless
`REPORT_PARSER_ENABLED=true` and a parser implementation is injected; the bundled bot
injects `None`.

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
that channel with the store and city, product, one of the exact labels `DROP`,
`IN STOCK`, `SOLD OUT`, or `NOTHING`, and the observed time as a Discord relative
timestamp. The embed contains no reporter name, hash, or mention, and the bot sends it
with `allowed_mentions=none`. Imported CSV rows are never posted to the feed.

If the channel is missing, permissions are wrong, or Discord rejects the post, the
bot logs a warning and returns the normal private confirmation; the report is never
rolled back. When a post succeeds, the private confirmation says it was shared
anonymously instead of saying nothing was posted publicly.

## Simulator

The simulator expects the six `EXAMPLE ...` stores from
`data/stores_example.csv` to be active. It refuses to run if its planted store names
are missing, so the real store seed cannot silently mix synthetic rows into them. Use
a development database and seed the example file first:

```bash
python scripts/seed_stores.py --csv data/stores_example.csv
```

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

## Store data

`data/stores_seed.csv` is the reviewed Southwest Florida store list: 106 stores
across Cape Coral, Fort Myers, Naples, Bonita Springs, Estero, and North Fort Myers.
It was normalized from the operator-supplied `data/SWFL_Retail_Locations.xlsx`
workbook (store name and full address only). Rows are validated for required fields,
known retailers, IANA timezone, duplicate `(retailer, name, address)` identities,
and paired coordinates before the database is opened.

The supplied workbook has no coordinates, so `lat` and `lng` are blank for every
row. The schema allows both coordinates to be absent, but never just one. Geocode
stores before enabling a radius feature; do not fill them with guessed values.

```bash
python scripts/seed_stores.py
```

The seed is idempotent and uses `(retailer, name, address)` as the natural key.
`data/stores_example.csv` keeps the six clearly fake `EXAMPLE ...` stores for
development and simulator work. Seed it only in a development database:

```bash
python scripts/seed_stores.py --csv data/stores_example.csv
```

The supplied list is a business-name/address list, not a live availability feed.
Store openings, closings, and whether a location carries Pokemon TCG are not
independently verified. Best Buy is not present in the supplied list, so it was not
added.

### Optional OSM candidate export (legacy)

```bash
python scripts/fetch_osm_stores.py
```

This legacy export makes one Overpass API request for the ten original supported
brands inside a bounding box covering Cape Coral, Fort Myers, Bonita Springs, and
Naples. It writes `data/stores_osm_candidates.csv` in the seed CSV format and never
connects to the database. The command refuses to overwrite an existing file unless
`--force` is passed.

Review and edit every row before using it. Rows with no OSM street or city are kept
so they are visible for review, but have blank fields until you fill them in. Then
merge reviewed rows into `data/stores_seed.csv` and run the normal seed command.
`scripts/seed_stores.py` rejects duplicate `(retailer, name, address)` rows and
prints created/updated totals.

OSM candidate data comes from OpenStreetMap, © OpenStreetMap contributors, available
under the [Open Database License](https://www.openstreetmap.org/copyright). This
attribution applies only to rows exported by that script, not to the supplied SWFL
list. No OSM data is inserted without review.

## CSV import

Historical observations collected outside Discord can be loaded with an
operator-reviewed CSV. The input columns are `observed_at_et`, `retailer`,
`store_hint`, `event`, `products`, `note`, `source`, and `confidence`. Dates are
ISO 8601; values without a timezone are treated as `America/New_York`.

Create a mapping file with `store_hint` and `store_id` columns. The importer
normalizes hints case-insensitively and whitespace-insensitively:

```csv
store_hint,store_id
Target Colonial Blvd,12
```

Run a dry run first. The command prints row counts and every unmatched hint, and it
exits nonzero without writing when a hint is unmatched or a row is invalid:

```bash
python scripts/import_observations_csv.py \
  --csv data/observations.csv \
  --mapping data/store_mapping.csv \
  --dry-run
```

Remove `--dry-run` to write the rows. Event mapping is `restock -> just_dropped`,
`in_stock -> in_stock`, `out_of_stock -> sold_out`, and `none -> nothing_here`.
`schedule_info` rows and rows with a blank date are skipped and counted. Imported rows
use `report_source=imported`, are stored under `csv:<source>` sources with the row's
confidence as the source trust weight, never appear in `/recent` or the public feed,
and never count toward Discord rate limits. The `products` column is mapped to the
primary product category; the original values remain in the row's `raw_text`.

## Cleanup example data

The default seed file now contains real stores. If a development database still has
the six demonstration stores and simulator rows, remove them after seeding:

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
migrations automatically. Service tests cover outcome validation, hashing,
store/outcome deduplication, rate limiting, recent-report queries, sold-out timing
across the New York midnight boundary, the free-text confirmation save path, CSV
import mapping and isolation, admin deletion/store activation, simulator persistence,
and source-scoped purge. Bot behavior is tested at the command parsing/formatting +
service seam, never by connecting to Discord.

CI runs Ruff, mypy, Alembic, and pytest against PostgreSQL 16.

## Decisions

- Deduplication is keyed by reporter hash, store, and outcome, using `reported_at`.
  A transaction-scoped PostgreSQL advisory lock serializes the check so simultaneous
  identical submissions cannot both pass. Product and quantity changes do not bypass
  the window.
- Reports store one of four outcomes: `just_dropped`, `in_stock`, `sold_out`, or
  `nothing_here`. The legacy `in_stock` boolean is derived from the outcome for
  compatibility. The `products` option maps to the existing primary product category;
  `quantity_note` and `raw_text` preserve the optional detail.
- Seed upserts use `(retailer, name, address)` as the natural key. Duplicate rows
  are rejected before the database is opened, with line numbers in the error.
- The primary store list is the operator-supplied SWFL workbook. It contains names
  and addresses only, so store coordinates are optional and stored as a pair. Missing
  coordinates stay null instead of being guessed from a ZIP code or city centroid.
- GameStop is a native retailer enum value because the supplied list includes nine
  GameStop locations. The enum migration adds it without rewriting existing rows.
- OSM store candidates remain an optional, one-time, single-request, read-only export
  for manual review. The script never seeds the database, and OSM data is attributed
  under ODbL. It is not the source of the supplied SWFL list.
- Example data cleanup is explicit (`--yes`), removes observations before stores,
  and also removes all `simulator`-source observations. It never removes sources or
  real user reports.
- Store autocomplete loads the active store set (currently 106) and ranks in
  Python because matching spans the retailer, name, city, and address and prefix
  matches must sort first. It returns at most 25 choices with case-insensitive
  token matching and truncates each label to Discord's 100-character limit.
- The public feed is opt-in through `LOCAL_RESTOCK_CHANNEL_ID`. The report service
  returns the announcement data (including store city), while a bot-layer notifier
  builds and posts the embed. Posting failures log a warning and return `False`; they
  never roll back the saved report. The embed has no reporter identity, uses the exact
  `DROP`, `IN STOCK`, `SOLD OUT`, or `NOTHING` label, sends with
  `allowed_mentions=none`, and renders observed time as a relative timestamp.
- Free-text parsing is behind `REPORT_PARSER_ENABLED` and dependency injection. The
  bundled `build_bot` injects `None`, so free text stays off until a `ReportParser`
  implementation exists. The confirmation view saves through the same report service
  with `report_source=freetext`; it never bypasses validation, deduplication, or rate
  limits.
- CSV imports use a user-edited `store_hint` to store ID mapping and refuse to write
  if any hint is unmatched. Imported rows are tagged `report_source=imported`, use
  `csv:<source>` source names, and are excluded from `/recent` and the feed. Because
  they bypass the Discord report service, they never consume a reporter's rate limit.
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
  Discord ingestion. The free-text parser is a typed seam only; no model is bundled.
- CSV import is manual and operator-reviewed. The mapping file must be edited by hand,
  and the `products` column is reduced to one primary product category for storage.
- Simulator patterns are tied to the example store names and only cover six stores.
- Crowdsourced reports are unverified. Source trust weights are stored but are not
  yet applied to predictions.
- No moderation queue, data-retention job, or scheduled jobs yet.
- Admin commands rely on Discord's default command permissions; a server administrator
  can override the default permission in Discord's integration settings.
- The supplied store list is operator-provided and format-validated, not independently
  verified for openings, closings, or Pokemon TCG inventory. It has no coordinates and
  does not include Best Buy.
- GitHub Actions has not run yet. Optionally configured feed/rate-limit/admin commands
  are tested locally but have not been exercised live until the bot is restarted.
