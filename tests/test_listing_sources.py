from types import SimpleNamespace

from niddo.listing_sources import PlaywrightListingClient
from niddo.models import Requirement


def _request(location: str) -> Requirement:
    return Requirement(
        location=location,
        price=3000000,
        area=60,
        bedrooms=2,
        parking_spaces=0,
        admin_fee=0,
        bathrooms=1,
        property_type="apartment",
    )


def test_direct_results_url_uses_neighborhood_before_city():
    client = PlaywrightListingClient(SimpleNamespace())

    url = client._direct_results_url(_request("Chapinero, Bogota"))

    assert url.endswith("/arriendo/apartamentos/chapinero/bogota-dc")


def test_direct_results_url_uses_neighborhood_when_city_comes_first():
    client = PlaywrightListingClient(SimpleNamespace())

    url = client._direct_results_url(_request("Bogota, Chapinero"))

    assert url.endswith("/arriendo/apartamentos/chapinero/bogota-dc")


def test_direct_results_url_infers_city_for_known_neighborhood():
    client = PlaywrightListingClient(SimpleNamespace())

    url = client._direct_results_url(_request("Chapinero"))

    assert url.endswith("/arriendo/apartamentos/chapinero/bogota-dc")


def test_direct_results_urls_prioritize_medellin_neighborhood_zone():
    client = PlaywrightListingClient(SimpleNamespace())

    urls = client._direct_results_urls(_request("Laureles, Medellín"))

    assert urls[0].endswith("/arriendo/apartamentos/laureles/occidente/medellin")
    assert urls[1].endswith("/arriendo/apartamentos/laureles-occidente/medellin")
    assert any(url.endswith("/arriendo/apartamentos/medellin/antioquia") for url in urls)


def test_location_fit_is_order_insensitive():
    client = PlaywrightListingClient(SimpleNamespace())

    assert client._location_fit("Bogota, Chapinero", "Chapinero, Bogota") == 1.0
