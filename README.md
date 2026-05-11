# Emmi kocht einfach Suche (Local, Dockerized)

Dockerized FastAPI web app that crawls public recipe pages from `emmikochteinfach.de`, indexes extracted recipe data into SQLite (FTS5), and provides a searchable local UI with recipe detail pages and source attribution.

## Highlights

- Starts from sitemap index: `https://emmikochteinfach.de/sitemap_index.xml`
- Handles sitemap indexes and nested sitemap files
- Polite crawler with:
  - `robots.txt` checks
  - configurable crawl delay and optional requests-per-minute limit
  - configurable retry/backoff for transient HTTP failures
- Structured recipe extraction via JSON-LD (`@type: Recipe`)
- Ignores page chrome by design (uses structured data, not full-page text scraping)
- SQLite + FTS5 full-text search
- Search by title, keywords, ingredients, instructions, categories
- Title matches weighted higher than body text
- Paginated search results
- Recipe detail page with source attribution link and `last indexed at` metadata
- Stale-content awareness (entries older than `CRAWLER_STALE_DAYS` are flagged)
- Cache-aware reindex decisions with retry cooldowns and refetch throttling
- CLI utilities for initial crawl, incremental reindex, and full reindex
- Structured JSON logging for crawl/parse/index/search operations
- One-command Docker startup with optional automatic reindex on boot
- Admin diagnostics pages (`/admin`, `/admin/index-status`) for completeness checks
- Local favorites with personal notes/comments (stored separately from scraped data), editable inline
- Tests for parser, search ranking behavior, and fixture integration flow

## Stack

- Python 3.12
- FastAPI
- Jinja2 templates + CSS
- SQLite + FTS5
- httpx + BeautifulSoup + lxml
- pytest
- Docker + docker-compose

## Crawl Scope and Safety

Implemented constraints:

- Crawl only allowed domain (`ALLOWED_DOMAIN`, default `emmikochteinfach.de`)
- Respect `robots.txt` (`can_fetch`) and optional crawl-delay directives
- Crawl politely using `CRAWLER_DELAY_SECONDS` and retries with backoff
- Prefer relevant sitemap files via:
  - `CRAWLER_INCLUDE_SITEMAP_KEYWORDS=post-sitemap,page-sitemap,recipe-sitemap` by default
- Parse and index only pages containing JSON-LD Recipe objects
- Do not index non-recipe pages
- Store and display original source URL for every indexed recipe
- Reindex logic refreshes missing, changed, or stale entries

## Extraction Strategy

Parser behavior is intentionally layered to improve quality and avoid page chrome:

1. Schema-first extraction
   - Prefer JSON-LD `@type: Recipe` for title, intro/description, times, servings, ingredients, instructions, and nutrition.
2. Noise stripping before DOM fallback
   - Remove known irrelevant blocks (`comments`, `author bio`, `newsletter`, `related/popular recipes`, social/share areas, `nav`, `footer`, sidebars).
3. Recipe-scoped DOM fallback
   - If JSON-LD fields are missing, fallback extraction is limited to recipe-focused containers/selectors (e.g. WPRM blocks) instead of full-page scraping.
4. Noise text filtering
   - Filter extracted text lines containing known non-recipe phrases (newsletter/comment/share/legal boilerplate).
5. Defensive indexing
   - Pages without actionable recipe body (`ingredients` and `instructions`) are skipped even if a `Recipe` node exists.

## Project Structure

```text
.
├── app
│   ├── crawler
│   │   ├── client.py
│   │   ├── indexer.py
│   │   ├── parser.py
│   │   └── sitemap.py
│   ├── search
│   │   └── service.py
│   ├── static
│   │   └── style.css
│   ├── templates
│   │   ├── admin_status.html
│   │   ├── base.html
│   │   ├── favorites.html
│   │   ├── index.html
│   │   └── recipe_detail.html
│   ├── config.py
│   ├── db.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   └── storage.py
├── scripts
│   └── manage.py
├── tests
│   ├── fixtures
│   │   ├── sample_non_recipe_page.html
│   │   └── sample_recipe_page.html
│   ├── conftest.py
│   ├── test_integration_fixture_flow.py
│   ├── test_indexer_cache_behavior.py
│   ├── test_favorites.py
│   ├── test_parser.py
│   ├── test_sitemap_discovery.py
│   ├── test_storage_diagnostics.py
│   ├── test_web_admin_and_favorites_routes.py
│   └── test_search.py
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pytest.ini
└── requirements.txt
```

## Data Model

Main table: `recipes`

- normalized recipe fields:
  - `title`, `intro`, `source_url`, `image_url`
  - `categories`, `published_date`
  - `prep_time`, `cook_time`, `total_time`, `servings`
  - `ingredients`, `instructions`
  - `nutrition_summary`
  - `searchable_text`
  - crawl metadata (`last_sitemap_mod`, `last_crawled_at`, `last_indexed_at`)

FTS table: `recipes_fts`

- full-text indexed columns:
  - `title`, `intro`, `categories_text`, `ingredients_text`, `instructions_text`, `searchable_text`
- trigger-based sync on insert/update/delete

Operational cache table: `crawl_state`

- stores per-URL crawl/index metadata:
  - `source_url`, `canonical_url`, `sitemap_url`, `sitemap_lastmod`
  - `last_fetched_at`, `last_parsed_at`
  - `content_hash` (change detection)
  - `index_status`, `last_error`
  - fetch/parse/skip counters for diagnostics

User table: `favorites`

- stores local user data separately from scraped content:
  - `recipe_id` (FK to `recipes`)
  - optional `note`/comment
  - timestamps

## Configuration

Copy env template:

```bash
cp .env.example .env
```

Important variables:

- `DATABASE_PATH` (default `./data/recipes.db`)
- `SITEMAP_INDEX_URL`
- `ALLOWED_DOMAIN`
- `CRAWLER_DELAY_SECONDS`
- `CRAWLER_RATE_LIMIT_PER_MINUTE`
- `CRAWLER_MAX_RETRIES`
- `CRAWLER_RETRY_BACKOFF_BASE_SECONDS`
- `CRAWLER_RETRY_BACKOFF_MAX_SECONDS`
- `CRAWLER_RETRY_JITTER_SECONDS`
- `CRAWLER_RETRY_STATUS_CODES`
- `CRAWLER_STALE_DAYS`
- `CRAWLER_MIN_FETCH_INTERVAL_HOURS`
- `CRAWLER_FAILURE_RETRY_HOURS`
- `CRAWLER_NON_RECIPE_RECHECK_DAYS`
- `CRAWLER_DISALLOWED_RECHECK_DAYS`
- `CRAWLER_INCLUDE_SITEMAP_KEYWORDS`
- `AUTO_REINDEX_ON_START`
- `AUTO_REINDEX_LIMIT`
- `RESULTS_PER_PAGE`

## Local Run (without Docker)

```bash
pip install -r requirements.txt
cp .env.example .env
python scripts/manage.py crawl --limit 100
uvicorn app.main:app --reload --host 0.0.0.0 --port 8910
```

Open: [http://localhost:8910](http://localhost:8910)

## Docker Run

```bash
cp .env.example .env
docker compose up -d --build
```

`docker compose up -d --build` starts the app and (by default) runs a startup reindex with `AUTO_REINDEX_LIMIT`.

Open: [http://localhost:8910](http://localhost:8910)

## Debian Server Run (without Docker)

A production-oriented Debian deployment is available in `deploy/debian`. It
installs the app into a Python virtual environment under `/opt/emmisuche`, runs
the web service with a hardened systemd unit, stores SQLite data under
`/var/lib/emmisuche`, and installs a cron job that reindexes every night at
01:00.

```bash
sudo deploy/debian/install.sh
```

See `deploy/debian/README.md` for the environment file, reverse-proxy example,
and security details.

## CLI Utilities

Initial crawl (missing only):

```bash
python scripts/manage.py crawl
```

Initial full indexing alias:

```bash
python scripts/manage.py index-full
```

Reindex stale/missing/changed:

```bash
python scripts/manage.py reindex
```

Force full refresh:

```bash
python scripts/manage.py reindex-all
```

Force full rebuild alias:

```bash
python scripts/manage.py rebuild-index
```

Diagnostics:

```bash
python scripts/manage.py index-status
```

Web diagnostics:

- HTML dashboard: `/admin` (alias: `/admin/status`)
- JSON diagnostics: `/admin/index-status`
- Includes:
  - crawl status breakdown (`indexed`, `non_recipe`, `fetch_failed`, `parse_failed`, `disallowed`, `new`)
  - stale recipe count
  - consistency checks (`indexed_without_recipe_total`, `recipe_without_state_total`)
  - recent crawl/parse failures

Optional flags:

- `--limit N`
- `--stale-days N` (for `reindex`)
- `--log-level DEBUG`

## Search Behavior

- Query is normalized into an FTS5 prefix query (`term* AND term*`)
- Search spans title/intro/categories/ingredients/instructions/searchable text
- Ranking uses weighted `bm25` with priority: title > ingredients > instructions > general body text
- Results include snippet, optional image, and source URL

## Cache and Stale Handling

- Reindex decisions are made from persisted `crawl_state` metadata.
- `reindex` fetches when one of these is true:
  - URL has no useful cache state yet
  - sitemap `lastmod` increased
  - cached entry is stale by policy (`CRAWLER_STALE_DAYS` for indexed content)
  - recent failure is outside retry cooldown (`CRAWLER_FAILURE_RETRY_HOURS`)
- To avoid unnecessary refetch loops, recently fetched URLs are throttled by
  `CRAWLER_MIN_FETCH_INTERVAL_HOURS` unless sitemap metadata indicates a change.
- `reindex-all` always forces fetch/parse refresh.
- URL cache lookup accepts trailing-slash variants to reduce duplicate fetches.

## Favorites and Notes

- Favorite/unfavorite from recipe detail pages
- Separate favorites page: `/favorites`
- Optional personal note per favorite recipe
- Notes can be edited inline on `/favorites` and from recipe detail
- Notes are stored in `favorites.note` and are never mixed into scraped recipe source fields

## Testing

```bash
pytest -q
```

Coverage focus:

- parser extraction correctness
- non-recipe rejection
- parser quality checks on saved real recipe fixtures
- title-vs-body ranking behavior
- integration-style fixture parse -> store -> search flow
- cache skip/retry edge cases and forced refresh behavior
- favorites + note persistence and route flows
- diagnostics consistency checks

## Assumptions

- Recipe data is primarily available in JSON-LD (`@type: Recipe`) on recipe pages.
- Non-recipe posts may exist in post sitemaps; they are filtered by parser result.
- This project is intended for local/personal use by default.

## Known Limitations

- Some recipe pages may have incomplete JSON-LD fields; missing fields are shown gracefully.
- Non-recipe pages are skipped, but still fetched when they appear in included sitemaps.
- No distributed crawl queue or advanced scheduling (intentionally simple architecture).
- Snippets use FTS output; highlighted fragments may be terse on very short matches.
- DOM structure changes on the source site can reduce fallback extraction quality until selectors are updated.
- Noise filtering is heuristic-based, so edge-case false positives/negatives are still possible.

## Make Commands

```bash
make install
make crawl
make reindex
make reindex-all
make update-stale
make run
make test
```

## CI

GitHub Actions workflow is included at `.github/workflows/tests.yml` and runs `pytest` on push and pull requests.
