from __future__ import annotations

import logging
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


def build_ui_text() -> dict[str, str]:
    return {
        "lang": "es",
        "page_title": "Niddo",
        "brief": "Resumen inmobiliario",
        "intro": (
            "Escribe la solicitud como la describiría un cliente. El flujo estructura la entrada, "
            "busca inmuebles, relaja restricciones cuando el mercado está apretado y prepara una recomendación final."
        ),
        "user_input": "Solicitud del usuario",
        "supporting": (
            "La versión actual prioriza la obtención de inmuebles y la calidad de la recomendación. "
            "La validación por WhatsApp sigue en espera."
        ),
        "run": "Ejecutar agente",
        "working": "Trabajando...",
        "error": "Error",
        "trace": "Trazabilidad",
        "no_report": "Todavía no hay reporte",
        "no_report_copy": "El reporte final aparecerá aquí cuando termine el grafo.",
        "loading_title": "Agente en ejecución",
        "loading_copy": "Buscando inmuebles, relajando restricciones cuando sea necesario y preparando el reporte final.",
        "steps": '["Analizando la solicitud...","Buscando inmuebles...","Revisando si hay que relajar restricciones...","Evaluando propiedades candidatas...","Armando el reporte final..."]',
        "toggle_label": "",
        "toggle_href": "#",
        "sample_text": (
            "Quiero arrendar un apartamento de 2 habitaciones en Bogotá por hasta 4.500.000 COP. "
            "Prefiero una zona caminable, cerca de transporte público y con buena luz natural."
        ),
        "empty_error": "Escribe una solicitud inmobiliaria antes de ejecutar el flujo.",
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
    ui = build_ui_text()
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
    language = "es"
    ui = build_ui_text()
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
        state = await run_in_threadpool(
            graph.invoke,
            {"raw_text": raw_text, "language": language, "retries": 0, "trace": []},
        )
        logger.info(
            "Workflow finished with listings=%s evaluation_passed=%s",
            len(state.get("listings", [])),
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
