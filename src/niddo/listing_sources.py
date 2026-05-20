from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from pathlib import Path
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from niddo.config import Settings
from niddo.models import Property, Requirement

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import Page, sync_playwright
except Exception:
    PlaywrightError = Exception
    Page = Any
    sync_playwright = None

logger = logging.getLogger("niddo.listing_sources")

FINCA_RAIZ_BASE_URL = "https://www.fincaraiz.com.co"
DEBUG_DIR = Path("debug")

@dataclass(slots=True)
class SearchResult:
    title: str
    url: str

class PlaywrightListingClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search(self, request: Requirement) -> list[Property]:
        if sync_playwright is None:
            logger.warning("Playwright is not available")
            return []
        if BeautifulSoup is None:
            logger.warning("beautifulsoup4 is not available")
            return []
            
        logger.info("Playwright search:start location=%s price=%s", request.location, request.price)
        
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.settings.browser_headless)
                context = browser.new_context()
                context.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in {"image", "font", "media"}
                    else route.continue_(),
                )
                page = context.new_page()
                page.set_default_timeout(self.settings.scrape_timeout_ms)
                
                results = self._search_results(page, request)
                logger.info("Playwright search:search_results=%s", len(results))
                
                properties: list[Property] = []
                for result in results:
                    logger.info("Playwright search:visiting %s", result.url)
                    details_page = context.new_page()
                    details_page.set_default_timeout(self.settings.scrape_timeout_ms)
                    try:
                        details_page.goto(result.url, wait_until="domcontentloaded")
                        property_item = self._extract_listing(details_page, result, request)
                        if property_item:
                            properties.append(property_item)
                    except PlaywrightError:
                        logger.exception("Playwright search:page visit failed for %s", result.url)
                    finally:
                        details_page.close()
                browser.close()
        except PlaywrightError:
            logger.exception("Playwright search failed")
            return []
            
        properties.sort(key=lambda item: item.score, reverse=True)
        return properties[: self.settings.search_results_limit]

    def _search_results(self, page: Page, request: Requirement) -> list[SearchResult]:
        results_url = self._direct_results_url(request)
        logger.info("FincaRaiz direct results url=%s", results_url)
        try:
            page.goto(results_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
        except PlaywrightError:
            logger.exception("FincaRaiz direct results page failed")
            return []

        results: list[SearchResult] = []
        seen: set[str] = set()
        anchors = page.locator(
            "a[href*='/apartamento-en-'], "
            "a[href*='/apartaestudio-en-'], "
            "a[href*='/casa-en-'], "
            "a[href*='/oficina-en-'], "
            "a[href*='/edificio-en-'], "
            "a[href*='/lote-en-']"
        )
        count = min(anchors.count(), self.settings.search_results_limit * 12)
        for index in range(count):
            href = anchors.nth(index).get_attribute("href") or ""
            title = (anchors.nth(index).text_content() or "").strip()
            normalized = self._normalize_url(href)
            if not normalized or normalized in seen:
                continue
            if "fincaraiz.com.co" not in normalized or "/inmuebles-colombia/" in normalized or "/blog/" in normalized or "/inmobiliarias/" in normalized:
                continue
            seen.add(normalized)
            results.append(SearchResult(title=title or normalized, url=normalized))
            if len(results) >= self.settings.search_results_limit * 3:
                break
        return results

    def _direct_results_url(self, request: Requirement) -> str:
        intent = "arriendo"
        property_slug = self._property_results_slug(request.property_type)
        city_slug = self._slugify(request.location.split(',')[0] if request.location else "bogota")
        region_slug = self._region_slug(request.location or "")
        return f"{FINCA_RAIZ_BASE_URL}/{intent}/{property_slug}/{city_slug}/{region_slug}"

    def _extract_listing(self, page: Page, result: SearchResult, request: Requirement) -> Property | None:
        html = page.content()
        metadata = self._extract_structured_candidates(html)
        best = self._pick_candidate(metadata)

        raw_text = page.locator("body").text_content() or ""
        
        price = self._extract_price(best) or self._extract_price_from_text(raw_text)
        if price is None:
            return None

        address = best.get("address")
        locality = self._address_field(address, "addressLocality")
        region = self._address_field(address, "addressRegion")
        
        parts = [p for p in (region, locality) if p]
        location_str = ", ".join(parts) if parts else request.location
        
        property_type = self._normalize_property_type(self._coalesce(best.get("@type"), best.get("category"), request.property_type))
        
        score = self._score_listing(price, location_str, request)
        
        # Fallback regex extraction for missing JSON-LD data
        facts = self._extract_property_facts(raw_text)
        bedrooms = self._extract_int(best, ("numberOfRooms", "numberOfBedrooms", "bedrooms")) or self._extract_regex_int(r"(\d+)\s*(hab|alcoba|dormitorio)", raw_text) or 0
        bathrooms = self._extract_int(best, ("numberOfBathroomsTotal", "bathrooms")) or self._extract_regex_int(r"(\d+)\s*baño", raw_text) or 0
        area = self._extract_area_value(best, raw_text, result.title)
        private_area = facts.get("private_area_m2")
        parking = self._extract_regex_int(r"(\d+)\s*(parqueadero|garaje)", raw_text) or 0
        admin_fee = self._extract_regex_int(r"(?:admin|administración).*?\$?\s?([\d\.\,]{4,})", raw_text) or 0
        
        return Property(
            location=location_str,
            price=int(price),
            area=float(area),
            private_area=float(private_area) if private_area else None,
            bedrooms=bedrooms,
            parking_spaces=parking,
            admin_fee=admin_fee,
            bathrooms=bathrooms,
            property_type=property_type,
            status=facts.get("status"),
            age_text=facts.get("age_text"),
            estrato=facts.get("estrato"),
            score=score,
            url=result.url
        )

    def _extract_property_facts(self, raw_text: str) -> dict[str, Any]:
        facts: dict[str, Any] = {}
        status = self._extract_regex_text(r"estado\s*[:\-]?\s*([a-záéíóúñ ]{3,30})", raw_text)
        if status:
            facts["status"] = status.title()

        age_text = self._extract_regex_text(
            r"antig[üu]edad\s*[:\-]?\s*([0-9]+\s*(?:a|hasta)\s*[0-9]+\s*años|[0-9]+\s*años?)",
            raw_text,
        )
        if age_text:
            facts["age_text"] = age_text

        estrato = self._extract_regex_int(r"estrato\s*[:\-]?\s*([1-9])", raw_text)
        if estrato:
            facts["estrato"] = estrato

        private_area = self._extract_regex_float(
            r"(?:área|area)\s*privada\s*[:\-]?\s*([\d\.,]+)\s*m(?:2|²)?",
            raw_text,
        )
        if private_area and private_area > 0:
            facts["private_area_m2"] = float(private_area)
        return facts

    def _extract_area_value(self, data: dict[str, Any], raw_text: str, title: str) -> float:
        structured_area = self._extract_area(data)
        if structured_area and structured_area > 0:
            return float(structured_area)

        area_patterns = (
            r"([\d\.,]+)\s*m(?:2|²)\b",
            r"area\s*(?:de)?\s*([\d\.,]+)",
            r"metraje\s*(?:de)?\s*([\d\.,]+)",
            r"([\d\.,]+)\s*metros?\s*cuadrados",
        )
        for pattern in area_patterns:
            parsed = self._extract_regex_float(pattern, raw_text)
            if parsed and parsed > 0:
                return float(parsed)

        title_area = self._extract_regex_float(r"([\d\.,]+)\s*m(?:2|²)\b", title)
        if title_area and title_area > 0:
            return float(title_area)

        return 0.0

    def _extract_regex_text(self, pattern: str, text: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        if not value:
            return None
        blocked = {"preguntale", "pregúntele", "preguntale!"}
        if value.lower() in blocked:
            return None
        return value

    def _extract_structured_candidates(self, html: str) -> list[dict[str, Any]]:
        if BeautifulSoup is None: return []
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        for script in soup.select("script[type='application/ld+json']"):
            raw = script.string or script.get_text(strip=True)
            if not raw: continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError: continue
            candidates.extend(self._flatten_json_ld(data))
        return candidates

    def _flatten_json_ld(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            items = []
            for entry in data: items.extend(self._flatten_json_ld(entry))
            return items
        if not isinstance(data, dict): return []
        graph = data.get("@graph")
        if isinstance(graph, list):
            items = []
            for entry in graph: items.extend(self._flatten_json_ld(entry))
            return items
        items = [data]
        offers = data.get("offers")
        if isinstance(offers, dict): items.append(offers)
        return items

    def _pick_candidate(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        scored = []
        for item in candidates:
            score = 0
            if item.get("price") or item.get("priceSpecification"): score += 3
            if item.get("name"): score += 2
            if item.get("address"): score += 2
            if item.get("@type"): score += 1
            scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[0][1] if scored else {}

    def _extract_price(self, data: dict[str, Any]) -> float | None:
        if "price" in data: return self._to_float(data.get("price"))
        price_spec = data.get("priceSpecification")
        if isinstance(price_spec, dict): return self._to_float(price_spec.get("price"))
        offers = data.get("offers")
        if isinstance(offers, dict): return self._to_float(offers.get("price"))
        return None

    def _extract_price_from_text(self, text: str) -> float | None:
        match = re.search(r"\$?\s?([\d\.\,]{6,})", text)
        return self._to_float(match.group(1)) if match else None

    def _extract_regex_int(self, pattern: str, text: str) -> int | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(self._to_float(match.group(1)) or 0)
            except ValueError:
                pass
        return None

    def _extract_regex_float(self, pattern: str, text: str) -> float | None:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return self._to_float(match.group(1))
        return None

    def _extract_int(self, data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = data.get(key)
            if value is not None:
                try: return int(float(str(value)))
                except ValueError: continue
        return None

    def _extract_area(self, data: dict[str, Any]) -> int | None:
        area = data.get("floorSize")
        if isinstance(area, dict): return int(self._to_float(area.get("value")) or 0)
        return int(self._to_float(data.get("area")) or 0)

    def _address_field(self, address: Any, key: str) -> str | None:
        return address.get(key) if isinstance(address, dict) and isinstance(address.get(key), str) else None

    def _normalize_property_type(self, raw: str) -> str:
        lowered = raw.lower()
        if "house" in lowered or "casa" in lowered: return "house"
        if "studio" in lowered or "apartaestudio" in lowered: return "studio"
        return "apartment"

    def _score_listing(self, price: float, location: str, request: Requirement) -> float:
        score = 0.2
        req_loc = request.location.lower()
        if req_loc in location.lower():
            score += 0.4
        if request.price:
            score += max(0.0, 0.4 - abs(price - request.price) / request.price)
        return round(score, 3)

    def _normalize_url(self, url: str) -> str:
        if not url: return ""
        if url.startswith("//"): return f"https:{url}"
        if url.startswith("http://") or url.startswith("https://"): return url
        if url.startswith("/"): return urljoin(FINCA_RAIZ_BASE_URL, url)
        return ""

    def _coalesce(self, *values: Any) -> str:
        for value in values:
            if isinstance(value, str) and value.strip(): return value.strip()
        return "Unknown"

    def _to_float(self, value: Any) -> float | None:
        if value is None: return None
        if isinstance(value, (int, float)): return float(value)
        cleaned = re.sub(r"[^\d,\.]", "", str(value))
        if not cleaned: return None
        if cleaned.count(",") == 1 and cleaned.count(".") > 1: cleaned = cleaned.replace(".", "").replace(",", ".")
        elif cleaned.count(",") > 1 and cleaned.count(".") == 0: cleaned = cleaned.replace(",", "")
        elif "," in cleaned and "." in cleaned: cleaned = cleaned.replace(".", "").replace(",", ".")
        else: cleaned = cleaned.replace(",", "")
        try: return float(cleaned)
        except ValueError: return None

    def _property_results_slug(self, property_type: str) -> str:
        mapping = {
            "apartment": "apartamentos",
            "house": "casas",
            "studio": "apartaestudios",
            "office": "oficinas",
            "land": "lotes"
        }
        return mapping.get(property_type.lower(), "apartamentos")

    def _region_slug(self, location: str) -> str:
        normalized = self._slugify(location)
        if "bogota" in normalized: return "bogota-dc"
        if "medellin" in normalized or "envigado" in normalized or "sabaneta" in normalized: return "antioquia"
        if "cali" in normalized: return "valle-del-cauca"
        return "colombia"

    def _slugify(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only.lower()).strip("-")
