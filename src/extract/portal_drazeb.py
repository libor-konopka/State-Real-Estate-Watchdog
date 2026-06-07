import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

from src.extract.base import BaseScraper
from src.schemas.estate import EstateSchema

logger = logging.getLogger(__name__)


class PortalDrazebScraper(BaseScraper):
    """
    Asynchronní extraktor pro portaldrazeb.cz.
    Aplikuje úvodní handshake pro zisk CSRF tokenu a PHPSESSID,
    následně těží celorepubliková data bez lokálních filtrů.
    """

    def __init__(self) -> None:
        super().__init__()
        self.api_url: str = "https://www.portaldrazeb.cz/drazby/pripravovane.json"
        self.limit: int = 20

    def _build_payload(self, offset: int) -> Dict[str, Any]:
        """Konstruuje datový záměr (všeobjímající tok pro kategorii 1)."""
        return {
            "filter": {
                "category": [1],
                "ruian": [],
                "county_auction": [],
                "county_item": [],
                "region_auction": [],
                "region_item": [],
                "min_price": 0,
                "max_price": 0,
                "sort": "asc",
                "sort_by": "start",
                "favourites_only": False,
                "start_at_from": "",
                "start_at_to": "",
                "limit": self.limit,
                "offset": offset,
                "page": (offset // self.limit) + 1,
            }
        }

    def _safe_datetime(self, date_str: Optional[str]) -> Optional[datetime]:
        """Bezpečně transformuje ISO string na datetime objekt."""
        if not date_str:
            return None
        try:
            clean_str = date_str.split(".")[0].split("+")[0]
            return datetime.fromisoformat(clean_str)
        except ValueError, TypeError, AttributeError:
            return None

    async def scrape(self, session: aiohttp.ClientSession) -> List[EstateSchema]:
        """Hlavní dech extraktoru vč. překonání CSRF ochrany."""
        logger.info(f"📡 {self.scraper_name}: Zahajuji inicializační handshake...")
        valid_items: List[EstateSchema] = []
        offset: int = 0
        csrf_token: Optional[str] = None

        # 1. Fáze: Zisk relační identity (Cookies + CSRF token)
        try:
            init_url = "https://www.portaldrazeb.cz/drazby/pripravovane"
            async with session.get(
                init_url, headers=self.get_default_headers()
            ) as resp:
                resp.raise_for_status()
                html_content = await resp.text()

                # Extrakce CSRF tokenu z meta tagu
                match = re.search(
                    r'<meta\s+name="csrf-token"\s+content="([^"]+)"',
                    html_content,
                    re.IGNORECASE,
                )
                if not match:
                    match = re.search(
                        r'<meta\s+content="([^"]+)"\s+name="csrf-token"',
                        html_content,
                        re.IGNORECASE,
                    )

                if match:
                    csrf_token = match.group(1)
                    logger.info(f"📡 {self.scraper_name}: CSRF Token úspěšně zachycen.")
                else:
                    logger.warning(
                        f"⚠️ {self.scraper_name}: CSRF Token nenalezen. Tok může být narušen."
                    )
        except aiohttp.ClientError as e:
            logger.error(f"Kritické selhání při handshake: {e}")
            return valid_items

        # 2. Fáze: Extrakční cyklus
        while True:
            payload = self._build_payload(offset)

            # Sestavení plnohodnotných hlaviček podle cURL vzoru
            headers = self.get_default_headers()
            headers.update(
                {
                    "Accept": "application/json",
                    "Content-Type": "application/json;charset=UTF-8",
                    "Origin": "https://www.portaldrazeb.cz",
                    "Referer": "https://www.portaldrazeb.cz/drazby/pripravovane",
                    "X-Requested-With": "XMLHttpRequest",
                }
            )

            if csrf_token:
                headers["x-csrf-token"] = csrf_token

            try:
                # Použití metody PUT dle požadavku serveru
                async with session.put(
                    self.api_url, json=payload, headers=headers
                ) as response:
                    response.raise_for_status()
                    data: Dict[str, Any] = await response.json()
            except aiohttp.ClientError as e:
                logger.error(f"Narušení toku na offsetu {offset}: {e}")
                break

            # Odstranění metadat '@count', ponechání pouze samotné hmoty inzerátů
            raw_items = [v for k, v in data.items() if k != "@count"]

            if not raw_items:
                logger.info(
                    f"{self.scraper_name}: Dosaženo prázdnoty na offsetu {offset}. Konec cyklu."
                )
                break

            logger.info(
                f"{self.scraper_name}: Transformuji {len(raw_items)} položek z offsetu {offset}."
            )

            for item in raw_items:
                parsed_estate = self._parse_item(item)
                if parsed_estate:
                    valid_items.append(parsed_estate)

            if len(raw_items) < self.limit:
                break

            offset += self.limit

        return valid_items

    def _parse_item(self, raw_data: Dict[str, Any]) -> Optional[EstateSchema]:
        """Transformuje surový fragment dat do našeho centrálního kontraktu."""
        try:
            item_info = raw_data.get("item", {})
            district_info = item_info.get("location_district") or {}

            region = district_info.get("county", {}).get("county_name")
            district = district_info.get("district_name")
            city = district_info.get("city", {}).get("city_name")

            seller = raw_data.get("auctioneer_office", {}).get("title")

            return EstateSchema(
                source_id=raw_data["hash"],
                source_portal="portaldrazeb.cz",
                title=item_info.get("title", "Neznámý název"),
                starting_price=raw_data.get("item_price"),
                estimated_price=raw_data.get("estimated_price"),
                location_region=region,
                location_district=district,
                location_city=city,
                cadastral_area=None,
                auction_start=self._safe_datetime(raw_data.get("start_at")),
                auction_end=self._safe_datetime(raw_data.get("end_at")),
                seller_institution=seller,
                url=raw_data.get(
                    "link", f"https://www.portaldrazeb.cz/drazba/{raw_data.get('hash')}"
                ),
                area_m2=None,
            )
        except KeyError as e:
            logger.warning(
                f"Chybějící kritický klíč {e} u záznamu {raw_data.get('hash')}"
            )
            return None
        except Exception as e:
            logger.warning(f"Chyba transformace záznamu {raw_data.get('hash')}: {e}")
            return None
