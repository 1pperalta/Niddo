from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from niddo.config import Settings
from niddo.models import AgentState, Requirement, Property, NewsItem, Proposal, EvalResult
from niddo.services import Services

logger = logging.getLogger("niddo.graph")


def build_graph(services: Services, settings: Settings):
    graph = StateGraph(AgentState)

    def intake_node(state: AgentState) -> dict:
        logger.info("Node intake:start")
        text_to_parse = state.user_text or state.raw_text or ""
        requirements = services.intake.parse_request(text_to_parse)
        logger.info("Node intake:done requirements_found=%s", len(requirements) if requirements else 0)
        return {
            "requirements": requirements,
            "retries": state.retries,
        }

    def coordinator_node(state: AgentState) -> dict:
        logger.info("Node coordinator:start")
        run_news = False
        if state.requirements:
            location = state.requirements[0].location.lower()
            if "bogota" in location or "medellin" in location:
                run_news = True
        logger.info("Node coordinator:done run_news=%s retries=%s", run_news, state.retries)
        return {
            "run_news": run_news,
        }

    def scraping_node(state: AgentState) -> dict:
        logger.info("Node scraper:start")
        properties = []
        feedback = ""
        
        if state.requirements:
            properties = services.listing.search(state.requirements[0])
            
        logger.info("Node scraper:done properties=%s", len(properties) if properties else 0)
        
        if not properties:
            feedback = "No properties matched the current requirements."
            
        return {
            "properties": properties,
            "feedback": feedback,
        }

    def chilling_node(state: AgentState) -> dict:
        logger.info("Node chilling:start")
        retry_count = state.retries + 1
        requirements = None
        if state.requirements:
            requirements = [services.intake.chill_request(state.requirements[0], state.feedback)]
        logger.info("Node chilling:done retry=%s", retry_count)
        return {
            "requirements": requirements,
            "retries": retry_count,
        }

    def news_node(state: AgentState) -> dict:
        logger.info("Node news:start")
        news_items = []
        if state.requirements:
            news_items = services.news.search(state.requirements[0], state.properties or [])
        logger.info("Node news:done insights=%s", len(news_items))
        return {
            "news_items": news_items,
        }

    def skip_news_node(state: AgentState) -> dict:
        logger.info("Node news-skip:done")
        return {
            "news_items": [],
        }

    def whatsapp_node(state: AgentState) -> dict:
        logger.info("Node whatsapp:start")
        validation = services.whatsapp.validate(state.properties or [])
        logger.info("Node whatsapp:done validations=%s", len(validation))
        return {} 

    def evaluator_node(state: AgentState) -> dict:
        logger.info("Node evaluator:start")
        evaluation = services.evaluation.evaluate(
            request=state.requirements[0] if state.requirements else None,
            listings=state.properties or [],
            news=state.news_items or [],
            threshold=settings.evaluation_threshold,
        )
        logger.info("Node evaluator:done passed=%s", evaluation.passed)
        return {
            "feedback": "; ".join(evaluation.required_fixes) if not evaluation.passed else "",
            "evaluation": evaluation,
        }

    def seller_node(state: AgentState) -> dict:
        logger.info("Node seller:start properties=%s", len(state.properties or []))
        if not state.evaluation:
            return {"html": "<p>Error: No evaluation provided.</p>"}
            
        proposal = services.seller.build_report(
            request=state.requirements[0] if state.requirements else None,
            listings=state.properties or [],
            news=state.news_items or [],
            evaluation=state.evaluation,
            language=state.language,
        )
        
        html = render_html(
            proposal=proposal,
            requirement=state.requirements[0] if state.requirements else None,
            news=state.news_items or [],
            evaluation=state.evaluation,
            language=state.language,
        )
        logger.info("Node seller:done html_len=%s", len(html))
        return {
            "proposals": [proposal],
            "html": html,
        }

    def no_results_node(state: AgentState) -> dict:
        logger.warning("Node no-results:triggered retries=%s", state.retries)
        evaluation = EvalResult(
            score=0.0,
            threshold=settings.evaluation_threshold,
            passed=False,
            reasons=["No viable listings were found after the configured retries."],
            required_fixes=[
                "Relajar presupuesto, área, o tipo de propiedad.",
                "Reducir filtros muy estrictos.",
            ],
        )
        return {
            "evaluation": evaluation,
        } 

    def retry_node(state: AgentState) -> dict:
        logger.info("Node retry:triggered current_retries=%s", state.retries)
        return {
            "retries": state.retries + 1,
        }

    def listings_route(state: AgentState) -> str:
        if state.properties:
            logger.info("Route scraper -> after_scrape")
            return "after_scrape"
        if state.retries >= settings.max_retries:
            logger.info("Route scraper -> no_results")
            return "no_results"
        logger.info("Route scraper -> chilling")
        return "chilling"

    def news_route(state: AgentState) -> str:
        route = "news" if state.run_news else "skip_news"
        logger.info("Route after_scrape -> %s", route)
        return route

    def evaluation_route(state: AgentState) -> str:
        if state.evaluation and state.evaluation.passed:
            logger.info("Route evaluator -> seller")
            return "seller"
        if state.retries >= settings.max_retries:
            logger.info("Route evaluator -> seller (max retries reached)")
            return "seller"
        logger.info("Route evaluator -> retry")
        return "retry"

    graph.add_node("intake", intake_node)
    graph.add_node("coordinator", coordinator_node)
    graph.add_node("scraper", scraping_node)
    graph.add_node("after_scrape", lambda state: state)
    graph.add_node("chilling", chilling_node)
    graph.add_node("no_results", no_results_node)
    graph.add_node("retry", retry_node)
    graph.add_node("news", news_node)
    graph.add_node("skip_news", skip_news_node)
    graph.add_node("whatsapp", whatsapp_node)
    graph.add_node("evaluator", evaluator_node)
    graph.add_node("seller", seller_node)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "coordinator")
    graph.add_edge("coordinator", "scraper")
    graph.add_conditional_edges(
        "scraper",
        listings_route,
        {
            "chilling": "chilling",
            "after_scrape": "after_scrape",
            "no_results": "no_results",
        },
    )
    graph.add_edge("chilling", "coordinator")
    graph.add_edge("no_results", "seller")
    graph.add_edge("retry", "coordinator")
    graph.add_conditional_edges(
        "after_scrape",
        news_route,
        {
            "news": "news",
            "skip_news": "skip_news",
        },
    )
    graph.add_edge("news", "whatsapp")
    graph.add_edge("skip_news", "whatsapp")
    graph.add_edge("whatsapp", "evaluator")
    graph.add_conditional_edges(
        "evaluator",
        evaluation_route,
        {
            "seller": "seller",
            "retry": "retry",
        },
    )
    graph.add_edge("seller", END)

    return graph.compile()

def _fit_reasons(prop: Property, requirement: Requirement | None, is_spanish: bool) -> list[str]:
    reasons: list[str] = []
    if not requirement:
        return reasons
    if prop.price <= requirement.price:
        reasons.append(
            f"Está dentro del presupuesto (${prop.price:,.0f} <= ${requirement.price:,.0f})."
            if is_spanish
            else f"It is within budget (${prop.price:,.0f} <= ${requirement.price:,.0f})."
        )
    if prop.bedrooms >= requirement.bedrooms:
        reasons.append(
            f"Cumple habitaciones ({prop.bedrooms} vs {requirement.bedrooms} requeridas)."
            if is_spanish
            else f"Matches bedrooms ({prop.bedrooms} vs {requirement.bedrooms} requested)."
        )
    if prop.bathrooms >= requirement.bathrooms:
        reasons.append(
            f"Cumple baños ({prop.bathrooms} vs {requirement.bathrooms} requeridos)."
            if is_spanish
            else f"Matches bathrooms ({prop.bathrooms} vs {requirement.bathrooms} requested)."
        )
    if prop.area >= requirement.area:
        reasons.append(
            f"Tiene buen metraje ({prop.area:.0f} m² vs {requirement.area:.0f} m² objetivo)."
            if is_spanish
            else f"Has good area ({prop.area:.0f} m² vs {requirement.area:.0f} m² target)."
        )
    if prop.parking_spaces >= requirement.parking_spaces:
        reasons.append(
            f"Incluye parqueadero ({prop.parking_spaces})."
            if is_spanish
            else f"Includes parking ({prop.parking_spaces})."
        )
    return reasons


def _tradeoffs(prop: Property, requirement: Requirement | None, is_spanish: bool) -> list[str]:
    tradeoffs: list[str] = []
    if not requirement:
        return tradeoffs
    if prop.price > requirement.price:
        over = prop.price - requirement.price
        tradeoffs.append(
            f"Supera el presupuesto en ${over:,.0f}."
            if is_spanish
            else f"Exceeds budget by ${over:,.0f}."
        )
    if prop.bedrooms < requirement.bedrooms:
        tradeoffs.append(
            "Tiene menos habitaciones de las solicitadas."
            if is_spanish
            else "Has fewer bedrooms than requested."
        )
    if prop.bathrooms < requirement.bathrooms:
        tradeoffs.append(
            "Tiene menos baños de los solicitados."
            if is_spanish
            else "Has fewer bathrooms than requested."
        )
    if prop.area < requirement.area:
        tradeoffs.append(
            "Metraje por debajo del objetivo."
            if is_spanish
            else "Area is below target."
        )
    if prop.parking_spaces < requirement.parking_spaces:
        tradeoffs.append(
            "Parqueaderos limitados."
            if is_spanish
            else "Limited parking spaces."
        )
    return tradeoffs


def _to_spanish_line(line: str) -> str:
    normalized = line.strip()
    lowered = normalized.lower()
    replacements = {
        "Budget fit": "Ajuste al presupuesto",
        "No viable listings were found after the configured retries.": "No se encontraron opciones viables después de los reintentos configurados.",
        "No results": "Sin resultados",
        "Need more options": "Se necesitan más opciones",
        "Raise budget": "Subir presupuesto",
    }
    for source, target in replacements.items():
        if normalized == source:
            return target

    phrase_replacements = {
        "budget": "presupuesto",
        "price": "precio",
        "within budget": "dentro del presupuesto",
        "over budget": "por encima del presupuesto",
        "location": "ubicación",
        "area": "zona",
        "bedrooms": "habitaciones",
        "bathrooms": "baños",
        "parking": "parqueadero",
        "listing": "inmueble",
        "listings": "inmuebles",
        "property": "propiedad",
        "properties": "propiedades",
        "matches": "coincide con",
        "does not match": "no coincide con",
        "doesn't match": "no coincide con",
        "fits": "encaja",
        "does not fit": "no encaja",
        "too restrictive": "demasiado restrictiva",
        "increase": "aumentar",
        "reduce": "reducir",
        "relax": "flexibilizar",
        "requested": "solicitado",
        "request": "solicitud",
        "more options": "más opciones",
        "no viable": "sin opciones viables",
        "found": "encontradas",
        "after retries": "después de los reintentos",
    }
    translated = normalized
    for source, target in phrase_replacements.items():
        translated = translated.replace(source, target).replace(source.title(), target.capitalize())

    english_markers = (" the ", " is ", " are ", " with ", " for ", " needs ", " should ", " not ")
    if any(marker in f" {translated.lower()} " for marker in english_markers):
        if "budget" in lowered or "price" in lowered:
            return "El presupuesto o precio debe ajustarse para mejorar la recomendación."
        if "location" in lowered or "area" in lowered or "neighborhood" in lowered:
            return "La ubicación o zona solicitada debe revisarse frente a las opciones disponibles."
        if "bedroom" in lowered or "bathroom" in lowered or "parking" in lowered:
            return "Las características del inmueble no coinciden completamente con lo solicitado."
        return "Hay un criterio pendiente por ajustar para mejorar la recomendación."
    return translated


def render_html(
    proposal: Proposal,
    requirement: Requirement | None,
    news: list[NewsItem],
    evaluation: EvalResult | None = None,
    language: str = "en",
) -> str:
    is_spanish = language == "es"
    cards = []
    top_properties = sorted(proposal.properties, key=lambda item: item.score, reverse=True)

    if not proposal.properties and evaluation and not evaluation.passed:
        fixes = "".join(
            f"<li>{_to_spanish_line(fix) if is_spanish else fix}</li>"
            for fix in evaluation.required_fixes
        )
        cards.append(
            (
                "<article class='card'><h3>No se encontraron propiedades</h3>"
                "<p>La búsqueda actual fue muy estricta. Sugerencias:</p>"
                f"<ul>{fixes}</ul></article>"
            )
            if is_spanish
            else (
                "<article class='card'><h3>No properties were found</h3>"
                "<p>The current search was too restrictive. Suggestions:</p>"
                f"<ul>{fixes}</ul></article>"
            )
        )
    
    type_map = {
        "apartment": "Apartamento",
        "house": "Casa",
        "studio": "Apartaestudio",
        "office": "Oficina",
        "land": "Lote",
        "any": "Propiedad"
    }
    
    for idx, prop in enumerate(top_properties, start=1):
        link_html = (
            f"<p><a class='listing-link' href='{prop.url}' target='_blank' rel='noreferrer'>"
            f"{'Ver publicación' if is_spanish else 'Open listing'}</a></p>"
            if prop.url
            else ""
        )
        es_type = type_map.get(prop.property_type.lower(), "Propiedad")
        fit_points = _fit_reasons(prop, requirement, is_spanish)
        tradeoff_points = _tradeoffs(prop, requirement, is_spanish)
        fit_html = (
            f"<p><strong>{'Por qué encaja' if is_spanish else 'Why it fits'}:</strong></p><ul>"
            + "".join(f"<li>{point}</li>" for point in fit_points[:3])
            + "</ul>"
            if fit_points
            else ""
        )
        tradeoff_html = (
            f"<p><strong>{'Aspectos a revisar' if is_spanish else 'Tradeoffs'}:</strong></p><ul>"
            + "".join(f"<li>{point}</li>" for point in tradeoff_points[:2])
            + "</ul>"
            if tradeoff_points
            else ""
        )
        cards.append(
            f"<article class='card'>"
            f"<p class='eyebrow'>{'Opción' if is_spanish else 'Option'} #{idx} · {'puntaje' if is_spanish else 'score'} {prop.score:.2f}</p>"
            f"<h3>{es_type if is_spanish else prop.property_type.title()} {'en' if is_spanish else 'in'} {prop.location}</h3>"
            f"<p class='price'>${prop.price:,.0f}</p>"
            f"{link_html}"
            f"<ul>"
            f"<li>{'Área' if is_spanish else 'Area'}: {prop.area} m²</li>"
            f"{f'<li>Área privada: {prop.private_area:.0f} m²</li>' if prop.private_area else ''}"
            f"<li>{'Habitaciones' if is_spanish else 'Bedrooms'}: {prop.bedrooms}</li>"
            f"<li>{'Baños' if is_spanish else 'Bathrooms'}: {prop.bathrooms}</li>"
            f"<li>{'Parqueaderos' if is_spanish else 'Parking spaces'}: {prop.parking_spaces}</li>"
            f"{f'<li>Estado: {prop.status}</li>' if prop.status else ''}"
            f"{f'<li>Antigüedad: {prop.age_text}</li>' if prop.age_text else ''}"
            f"{f'<li>Estrato: {prop.estrato}</li>' if prop.estrato else ''}"
            f"</ul>"
            f"{fit_html}"
            f"{tradeoff_html}"
            f"</article>"
        )

    news_html = ""
    if news:
        news_items = "".join(
            f"<li><strong>{item.source}:</strong> {item.text} <br><small>{item.summary}</small></li>"
            for item in news[:5]
        )
        news_html = (
            f"<section class='panel'><h2>Noticias relevantes por zona</h2><ul>{news_items}</ul></section>"
            if is_spanish
            else f"<section class='panel'><h2>Location news signals</h2><ul>{news_items}</ul></section>"
        )

    req_html = ""
    if requirement:
        req_html = (
            f"<p>Buscando en: {requirement.location} (Presupuesto: ${requirement.price:,.0f})</p>"
            if is_spanish
            else f"<p>Search area: {requirement.location} (Budget: ${requirement.price:,.0f})</p>"
        )

    eval_html = ""
    if evaluation:
        if is_spanish:
            reasons = "".join(f"<li>{_to_spanish_line(reason)}</li>" for reason in evaluation.reasons[:4])
            required_fixes = "".join(f"<li>{_to_spanish_line(fix)}</li>" for fix in evaluation.required_fixes[:4])
        else:
            reasons = "".join(f"<li>{reason}</li>" for reason in evaluation.reasons[:4])
            required_fixes = "".join(f"<li>{fix}</li>" for fix in evaluation.required_fixes[:4])
        fix_block = (
            f"<p><strong>{'Ajustes sugeridos' if is_spanish else 'Suggested fixes'}:</strong></p><ul>{required_fixes}</ul>"
            if required_fixes
            else ""
        )
        eval_html = (
            f"<section class='panel'><h2>{'Evaluación de la recomendación' if is_spanish else 'Recommendation evaluation'}</h2>"
            f"<p>{'Puntaje' if is_spanish else 'Score'}: {evaluation.score:.2f} "
            f"({'>=' if evaluation.passed else '<'} {evaluation.threshold:.2f})</p>"
            f"<ul>{reasons}</ul>{fix_block}</section>"
        )

    return f"""
    <section class="report">
      <header class="hero">
        <p class="eyebrow">{'Propuesta de Niddo' if is_spanish else 'Niddo proposal'}</p>
        <h1>{'Recomendaciones de propiedades' if is_spanish else 'Property recommendations'}</h1>
        {req_html}
        <div class="meta">
          <span>{'Puntaje de propuesta' if is_spanish else 'Proposal score'}: {proposal.score:.2f}</span>
          <span>{'Propiedades evaluadas' if is_spanish else 'Evaluated properties'}: {len(top_properties)}</span>
          <span>{'Señales de noticias' if is_spanish else 'News signals'}: {len(news)}</span>
        </div>
      </header>
      <section class="cards">{''.join(cards)}</section>
      {eval_html}
      {news_html}
    </section>
    """
