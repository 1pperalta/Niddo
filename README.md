# niddo

Real-estate agent built with LangGraph, Pydantic, and OpenAI.

## Stack

- Python 3.11+
- LangGraph for orchestration
- OpenAI Responses API for structured parsing, evaluation, and report generation
- Pydantic v2 for contracts
- FastAPI for the web app (Server-Side Rendering with Jinja2)

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

## Current status

- **Unified Pydantic State**: The entire LangGraph workflow is orchestrated using a single, serializable Pydantic model (`AgentState`), ensuring type safety and consistency across all nodes.
- **English-Spanish Schema**: The core logic and variable names follow strict English project conventions, while the user-facing output is dynamically rendered in Spanish or English based on user preference.
- **Composite News Agent**: The news agent is now a concurrent composite agent. It executes multiple parallel Spanish queries to Tavily, covering specific dimensions:
    - **Movilidad/Transporte**: Transporte público, tráfico y acceso.
    - **Seguridad**: Reportes de seguridad local.
    - **Comercialización**: Proximidad a zonas comerciales.
    - **Vida Nocturna**: Bares, restaurantes y actividad social.
    - **Riesgos Ambientales**: Inundaciones y riesgos climáticos.
- **Structured Parsing & Evaluation**: Uses OpenAI structured outputs to map user instructions into a detailed `Requirement` list and evaluate `Property` candidates against a quality threshold.
- **Automated Graph Visualization**: Includes logic to generate Mermaid diagrams of the system's internal orchestration and the news agent's concurrent logic.

## Next

- Refactor the `PlaywrightListingClient` to fully support the new Pydantic requirement/property schemas.
- Integrate **NewsAPI** or **GDELT** into the composite news agent for deeper coverage.
- Add persistence for runs, traces, and generated reports.
