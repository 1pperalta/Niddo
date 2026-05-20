from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import parse_qs

from fastapi.concurrency import run_in_threadpool
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from niddo.config import settings
from niddo.graph import build_graph
from niddo.logging_utils import configure_logging
from niddo.services import (
    OpenAIWorkflowService,
    PlaywrightListingService,
    Services,
    StandbyWhatsAppService,
    TavilyNewsService,
)


configure_logging(settings.log_level)
logger = logging.getLogger("niddo.app")
templates = Jinja2Templates(directory="src/niddo/templates")
app = FastAPI(title=settings.app_name)


def build_ui_text(language: str) -> dict[str, str]:
    is_spanish = language == "es"
    return {
        "lang": language,
        "page_title": "Niddo",
        "brief": "Resumen inmobiliario" if is_spanish else "Real estate brief",
        "intro": (
            "Escribe la solicitud como la describiría un cliente. El flujo estructura la entrada, "
            "busca inmuebles, relaja restricciones cuando el mercado está apretado y prepara una recomendación final."
            if is_spanish
            else "Write the request as a client would describe it. The workflow structures the input, "
            "searches listings, relaxes constraints when the market is tight, and prepares a final recommendation."
        ),
        "user_input": "Solicitud del usuario" if is_spanish else "User request",
        "supporting": (
            "La versión actual prioriza la obtención de inmuebles y la calidad de la recomendación. "
            "La validación por WhatsApp sigue en espera."
            if is_spanish
            else "Current version prioritizes listing retrieval and recommendation quality. "
            "WhatsApp validation remains on standby."
        ),
        "run": "Ejecutar agente" if is_spanish else "Run workflow",
        "working": "Trabajando..." if is_spanish else "Working...",
        "error": "Error",
        "trace": "Trazabilidad" if is_spanish else "Trace",
        "no_report": "Todavía no hay reporte" if is_spanish else "No report yet",
        "no_report_copy": (
            "El reporte final aparecerá aquí cuando termine el grafo."
            if is_spanish
            else "The final report will appear here when the graph finishes."
        ),
        "loading_title": "Agente en ejecución" if is_spanish else "Agent running",
        "loading_copy": (
            "Buscando inmuebles, relajando restricciones cuando sea necesario y preparando el reporte final."
            if is_spanish
            else "Searching listings, relaxing constraints when needed, and preparing the final report."
        ),
        "loading_slow": (
            "La búsqueda está tardando más de lo normal. Seguimos procesando..."
            if is_spanish
            else "The search is taking longer than usual. We are still processing..."
        ),
        "steps": (
            '["Analizando la solicitud...","Buscando inmuebles...","Revisando si hay que relajar restricciones...","Evaluando propiedades candidatas...","Armando el reporte final..."]'
            if is_spanish
            else '["Parsing request...","Searching listings...","Checking constraints...","Evaluating candidates...","Preparing final report..."]'
        ),
        "toggle_label": "",
        "toggle_href": "#",
        "sample_text": (
            "Quiero arrendar un apartamento de 2 habitaciones en Bogotá por hasta 4.500.000 COP. "
            "Prefiero una zona caminable, cerca de transporte público y con buena luz natural."
            if is_spanish
            else "I want to rent a 2-bedroom apartment in Medellin up to 4,500,000 COP, "
            "preferably walkable and near public transport."
        ),
        "empty_error": (
            "Escribe una solicitud inmobiliaria antes de ejecutar el flujo."
            if is_spanish
            else "Write a property request before running the workflow."
        ),
    }


def build_services() -> Services:
    logger.info("Building services with listing_mode=%s", settings.listing_mode)
    workflow = OpenAIWorkflowService(settings)
    return Services(
        intake=workflow,
        evaluation=workflow,
        seller=workflow,
        listing=PlaywrightListingService(settings),
        news=TavilyNewsService(settings),
        whatsapp=StandbyWhatsAppService(),
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    logger.info("Rendering home page")
    language = settings.content_language
    ui = build_ui_text(language)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "title": ui["page_title"],
            "result_html": None,
            "trace": [],
            "error": None,
            "raw_text": ui["sample_text"],
            "ui": ui,
        },
    )


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.post("/run", response_class=HTMLResponse)
async def run_workflow(request: Request) -> HTMLResponse:
    body = await request.body()
    form = parse_qs(body.decode("utf-8"))
    raw_text = form.get("raw_text", [""])[0].strip()
    requested_language = form.get("language", [settings.content_language])[0].strip().lower()
    language = requested_language if requested_language in {"es", "en"} else settings.content_language
    ui = build_ui_text(language)
    logger.info("Received workflow request")
    if not raw_text:
        logger.warning("Workflow request arrived without raw_text")
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "title": ui["page_title"],
                "result_html": None,
                "trace": [],
                "error": ui["empty_error"],
                "raw_text": raw_text,
                "ui": ui,
            },
        )
    try:
        services = build_services()
        graph = build_graph(services, settings)
        logger.info("Invoking LangGraph workflow")
        start_ts = time.perf_counter()
        state = await asyncio.wait_for(
            run_in_threadpool(
                graph.invoke,
                {"raw_text": raw_text, "language": language, "retries": 0, "trace": []},
            ),
            timeout=settings.workflow_timeout_s,
        )
        elapsed = time.perf_counter() - start_ts
        logger.info(
            "Workflow finished in %.2fs with properties=%s evaluation_passed=%s",
            elapsed,
            len(state.get("properties", [])),
            state.get("evaluation").passed if state.get("evaluation") else None,
        )
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "title": ui["page_title"],
                "result_html": state.get("html"),
                "trace": state.get("trace", []),
                "error": None,
                "raw_text": raw_text,
                "ui": ui,
            },
        )
    except asyncio.TimeoutError:
        logger.exception("Workflow timed out after %ss", settings.workflow_timeout_s)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "title": ui["page_title"],
                "result_html": None,
                "trace": [],
                "error": (
                    "La ejecución tardó demasiado y se detuvo para evitar que la pantalla quede bloqueada. "
                    "Intenta una búsqueda más específica o vuelve a ejecutar."
                ),
                "raw_text": raw_text,
                "ui": ui,
            },
        )
    except Exception as exc:
        logger.exception("Workflow execution failed")
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "title": ui["page_title"],
                "result_html": None,
                "trace": [],
                "error": str(exc),
                "raw_text": raw_text,
                "ui": ui,
            },
        )
