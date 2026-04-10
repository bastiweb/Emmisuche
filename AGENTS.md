# AGENTS.md

## Project purpose
This repository contains a Dockerized web application that indexes and searches recipe content from `emmikochteinfach.de`.

Primary user value:
- search recipes quickly by title, keyword, ingredient, or category-like terms
- open a clean recipe detail page inside the app
- avoid unnecessary re-crawling by reusing stored/indexed content whenever possible
- support future personal features such as favorites and user notes/comments on saved recipes

## How to work in this repository
- Make minimal, targeted changes.
- Follow the existing stack and patterns already present in the repository.
- Prefer extending current modules over introducing parallel implementations.
- Do not perform broad refactors unless explicitly requested.
- Keep the app simple, maintainable, and easy to run locally with Docker.
- When a task is larger than a small patch, first explain the implementation plan briefly, then execute it.

## Source of truth
When deciding how to implement something, prioritize these in order:
1. Existing tests
2. Existing application structure and code patterns
3. Docker and environment configuration already present in the repo
4. README and project docs
5. This file

If this file conflicts with the established implementation already in the repository, preserve the existing implementation style unless the user explicitly requests a change.

## Architecture expectations
Prefer a modular structure with clearly separated concerns:
- crawler / sitemap discovery
- HTML fetching
- recipe parsing / extraction
- persistence / database
- search / ranking
- web UI / routes / templates
- user features such as favorites and notes
- config

Parsing and crawling logic should remain isolated and testable.

## Product rules
### 1) Search behavior
- Search should use the local index/database, not live-fetch the target site on every user search.
- Searching must remain fast and deterministic.
- Title matches should rank above broader body matches.
- Ingredient matches should be treated as highly relevant.
- Return concise snippets and preserve source attribution.

### 2) Caching and indexing
- Do not re-fetch a recipe page if equivalent usable data is already stored locally, unless a reindex or refresh flow explicitly requires it.
- Prefer incremental indexing over full re-crawls.
- Add or preserve timestamps such as `indexed_at`, `last_fetched_at`, or similar if the schema supports them.
- Any refresh logic should be explicit, configurable, and polite.
- Avoid duplicate URL records and duplicate search documents.

### 3) Recipe extraction quality
Extract and store the recipe core only when possible:
- title
- intro/subtitle
- canonical/source URL
- image URL if present
- category/breadcrumbs if present
- published date if present
- prep/cook/total time if present
- servings if present
- ingredients
- instructions/steps
- nutrition summary if present

Explicitly avoid indexing irrelevant page chrome such as:
- navigation
- footer
- newsletter/signup sections
- related recipes blocks
- author biography blocks
- comment sections
- social sharing blocks
- generic promotional text

### 4) Favorites and personal notes
This feature may be added later or expanded incrementally.
When implementing favorites/user notes:
- keep it local-first and simple
- store favorites separately from crawled recipe source data
- do not mix user-authored notes into the main search document unless explicitly intended
- preserve a clean boundary between scraped content and user-generated content
- support easy future extension for comments, change notes, or “cook again” style annotations

### 5) Attribution and scope
- Always preserve and display the original source URL.
- The app should operate on public pages from the target domain only, unless the user explicitly broadens the scope.
- Keep the app suitable for personal/local use by default.

## Crawling rules
- Respect `robots.txt` and sitemap structure.
- Crawl politely with rate limiting.
- Use retries/backoff conservatively.
- Do not introduce aggressive concurrency by default.
- Prefer sitemap-guided discovery over blind crawling.
- Canonicalize URLs where practical.
- Log crawl and parse failures clearly without crashing the full indexing run.

## Technical preferences
Unless the repository already chose differently, prefer:
- Python 3.12
- FastAPI
- server-rendered templates
- SQLite with FTS5 for search
- `httpx` + `BeautifulSoup`/`lxml` for fetching and parsing
- `pytest` for tests
- Docker / docker compose for local execution

Do not add heavy infrastructure such as Elasticsearch, Redis, Celery, or a frontend SPA unless the user explicitly asks for it.

## Data and schema guidance
- Keep the schema simple and normalized.
- Separate recipe source records from user data such as favorites or notes.
- Use migrations or migration-like patterns if the project already has them.
- Preserve backward compatibility for existing data when feasible.

## UI guidance
- Prefer clean, fast, readable UI over flashy design.
- Keep HTML/CSS simple.
- Recipe detail pages should prioritize readability.
- Search pages should prioritize speed, clarity, and useful snippets.
- Admin/indexing controls, if present, should remain basic and safe.

## Testing expectations
For meaningful changes:
- add or update tests for parser behavior when extraction logic changes
- add or update tests for search behavior when ranking/search logic changes
- add or update tests for favorites/notes when user data behavior changes
- prefer fixtures for real-world HTML samples when testing parsing

Before finishing:
- run relevant tests
- run lint/format checks if configured
- summarize changed files and any known limitations

## Safety rails for edits
- Do not rewrite unrelated files.
- Do not silently change the chosen stack.
- Do not remove source attribution.
- Do not make search depend on real-time scraping for normal usage.
- Do not index comments or unrelated page content on purpose.
- Do not store secrets in the repository.
- Do not hardcode environment-specific paths or credentials.

## Definition of done
A task is done when:
- the requested behavior works end to end
- the implementation follows the repo's established structure
- the change is as small as reasonably possible
- tests relevant to the change pass or are updated appropriately
- documentation is updated when behavior or setup changed
- any limitations or assumptions are clearly stated

## Collaboration notes for Codex
When making non-trivial changes, end with:
- a short summary of what changed
- files changed
- commands run
- risks, follow-ups, or known limitations

If a requested feature is not yet implemented, build the smallest clean foundation that supports future extension instead of overengineering.
