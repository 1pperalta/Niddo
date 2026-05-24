from types import SimpleNamespace

from niddo.models import (
    Listing,
    ListingLocation,
    ListingProperty,
    Location,
    NewsItem,
    Property,
    PropertyType,
    Requirement,
    UserRequest,
)
from niddo.services import TavilyNewsService, normalize_text


def test_normalize_text_strips_accents_and_spacing():
    assert normalize_text("  Bogotá Norte  ") == "bogota norte"


def test_tavily_neighborhood_helpers_use_request_and_listings():
    request = UserRequest(
        raw_text="need options",
        search_summary="broad request",
        location=Location(city="Bogota"),
    )
    listings = [
        Listing(
            id="med-001",
            source="test",
            url="https://example.com/med-001",
            title="Laureles apartment",
            price=3200000,
            location=ListingLocation(city="Medellin", neighborhood="Laureles"),
            property=ListingProperty(type=PropertyType.APARTMENT, bedrooms=2, bathrooms=2),
        )
    ]
    service = TavilyNewsService(settings=SimpleNamespace(tavily_api_key=None, news_results_limit=5))

    neighborhoods = service._candidate_neighborhoods(request, listings)
    queries = service._build_queries(service._candidate_news_scopes(request, listings))

    assert "Laureles" in neighborhoods
    assert any("ciudad de Bogota" in query for query in queries)
    assert any("barrio o zona Laureles, Medellin" in query for query in queries)
    assert all("en español" in query for query in queries)


def test_tavily_build_insights_keeps_spanish_news_only():
    service = TavilyNewsService(settings=SimpleNamespace(tavily_api_key=None, news_results_limit=5))
    response = {
        "results": [
            {
                "title": "Seguridad en Chapinero mejora con mas policia",
                "content": "La ciudad refuerza seguridad y movilidad en el barrio durante la noche.",
                "source": "Local",
            },
            {
                "title": "New restaurants open in Bogota",
                "content": "The neighborhood has more nightlife and traffic this month.",
                "source": "Wire",
            },
        ]
    }

    items = service._build_insights(response)

    assert items == [
        NewsItem(
            source="Local",
            text="Seguridad en Chapinero mejora con mas policia",
            summary="La ciudad refuerza seguridad y movilidad en el barrio durante la noche.",
        )
    ]


def test_news_search_uses_duckduckgo_without_tavily_key(monkeypatch):
    service = TavilyNewsService(settings=SimpleNamespace(tavily_api_key=None, news_results_limit=1))
    duck_item = NewsItem(
        source="Duck",
        text="Movilidad mejora en Chapinero",
        summary="La ciudad anuncia cambios de transporte en la zona.",
    )
    monkeypatch.setattr(service, "_fetch_duckduckgo_query", lambda query: [duck_item])
    request = Requirement(
        location="Chapinero, Bogota",
        price=3000000,
        area=60,
        bedrooms=2,
        parking_spaces=0,
        admin_fee=0,
        bathrooms=1,
        property_type="apartment",
    )
    listings = [
        Property(
            location="Bogota, Chapinero",
            price=2800000,
            area=62,
            bedrooms=2,
            parking_spaces=0,
            admin_fee=0,
            bathrooms=1,
            property_type="apartment",
            score=0.9,
        )
    ]

    items = service.search(request, listings)

    assert items == [duck_item]
