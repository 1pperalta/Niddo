# niddo

Real-estate recommendation workflow built with LangGraph, FastAPI, Pydantic, OpenAI,
Playwright, Tavily, and DuckDuckGo.

## Stack

- Python 3.11+
- LangGraph for orchestration
- OpenAI Responses API for structured parsing, evaluation, and report generation
- Pydantic v2 for contracts
- FastAPI for the web app (Server-Side Rendering with Jinja2)
- Playwright + BeautifulSoup for listing discovery and extraction
- Tavily + DuckDuckGo for location news signals

## Run

```bash
uv venv
source .venv/bin/activate
uv sync --extra dev
uv run playwright install chromium
uv run uvicorn niddo.app:app --reload --app-dir src
```

Open `http://127.0.0.1:8000`.

If `OPENAI_API_KEY` is already in `.env`, the app will load it automatically.
If you want the news agent to use Tavily, also set `TAVILY_API_KEY` in `.env`.
DuckDuckGo is used as a secondary news source and as a fallback when Tavily is not configured.

Useful environment variables:

- `OPENAI_API_KEY`: required for the default OpenAI provider.
- `TAVILY_API_KEY`: optional; enables Tavily news search.
- `NIDDO_CONTENT_LANGUAGE`: defaults to `es`.
- `NIDDO_FAST_MODEL`: defaults to `gpt-5-nano`.
- `NIDDO_QUALITY_MODEL`: defaults to `gpt-5-mini`.
- `NIDDO_EVALUATION_THRESHOLD`: defaults to `0.72`.
- `NIDDO_MAX_RETRIES`: defaults to `1`.
- `NIDDO_BROWSER_HEADLESS`: defaults to `true`.
- `NIDDO_SCRAPE_TIMEOUT_MS`: defaults to `20000`.
- `NIDDO_SEARCH_RESULTS_LIMIT`: defaults to `5`.

## Current status

- **Typed LangGraph workflow**: The workflow is orchestrated with a single serializable
  Pydantic state model (`AgentState`) and typed node/service boundaries.
- **Spanish-first user experience**: The default UI and final report are Spanish. The
  evaluator is instructed to return Spanish reasons and fixes, and the HTML renderer
  sanitizes common English fallback text before displaying it.
- **Visible loading state**: The web app shows an execution overlay before submitting
  the request, so long Playwright/OpenAI runs do not look frozen.
- **Weighted recommendation scoring**: Listing scores use a linear weighted model based
  on the criteria present in the user's request. Price receives the highest base
  priority when provided, while location, bedrooms, bathrooms, area, parking, and
  property type are normalized across active criteria.
- **Neighborhood-aware scraping**: FincaRaiz search URLs preserve neighborhood intent.
  Locations such as `Chapinero, Bogota`, `Bogota, Chapinero`, and `Chapinero` resolve
  to neighborhood-focused searches instead of falling back to a city-only query.
- **Medellin neighborhood fallbacks**: Known Medellin neighborhoods use FincaRaiz route
  variants before generic department routes. For example, `Laureles, Medellin` tries
  `laureles/occidente/medellin`, `laureles-occidente/medellin`,
  `laureles/antioquia`, and then `medellin/antioquia`.
- **Composite news agent**: The news agent runs concurrent Spanish queries for both
  city and neighborhood scopes. It uses Tavily when configured and DuckDuckGo as a
  secondary/fallback source. English-looking results are filtered before rendering.
  Covered dimensions include:
  - Mobility and public transport.
  - Safety and local crime signals.
  - Commerce and nearby services.
  - Nightlife, restaurants, and social activity.
  - Environmental risks, flooding, and weather.
- **Structured parsing, relaxation, and evaluation**: OpenAI structured outputs convert
  free-form user instructions into `Requirement` objects, relax constraints after
  empty searches, evaluate candidates against a threshold, and generate the final
  proposal HTML.
- **Automated graph visualization**: Mermaid diagrams document the workflow and the
  concurrent news-search strategy.

## Tests

```bash
uv run pytest
```

The current test suite covers graph routing, service helpers, neighborhood URL
normalization, news filtering/fallbacks, and Spanish rendering behavior.

## Next

- Refactor the `PlaywrightListingClient` to fully support the new Pydantic requirement/property schemas.
- Add persistence for runs, traces, and generated reports.
