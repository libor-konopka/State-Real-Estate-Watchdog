import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp

from src.extract.base import BaseScraper
from src.schemas.estate import EstateSchema

logger = logging.getLogger(__name__)


class NabidkaMajetkuScraper(BaseScraper):
    """
    Asynchronní extraktor pro nabidkamajetku.gov.cz (ÚZSVM).
    Napojuje se na interní API /api/Property/List.
    Zachycuje veškerou hmotu (pozemky a stavby) bez geografického omezení.
    """

    def __init__(self) -> None:
        super().__init__()
        self.api_url: str = "https://nabidkamajetku.gov.cz/api/Property/List"
        self.page_size: int = 25
        # Geografický filtr (self.target_districts) byl odstraněn.

    def _build_payload(self, page: int, category_id: str) -> Dict[str, Any]:
        """Konstruuje datový záměr. Nyní dynamicky přijímá ID kategorie."""
        return {
            "ListType": "all",
            "Page": page,
            "PageSize": self.page_size,
            "Order": "Default",
            "OrderDesc": "true",
            "CategoryId": category_id,
            "CadastreId": "0",
            "ContactZipCode": "",
            "Fulltext": "",
            "InterestId": "0",
            "LocalityId": "0",
            "MunicipialityId": "0",
            "MyinterestId": 0,
            "OrgId": "",
            "OrganizationId": "0",
            "OrganizationType": "0",
            "PropertyAuthor": "",
            "ShowEndedProperties": False,
            "State": "0",
        }

    def _parse_price(self, price_str: Optional[str]) -> Optional[float]:
        """Očistí textovou strukturu ('3 621 888,00') a přetaví ji na desetinné číslo."""
        if not price_str:
            return None
        try:
            clean_str = price_str.replace(" ", "").replace("\xa0", "").replace(",", ".")
            return float(clean_str)
        except ValueError:
            return None

    def _parse_dates(
        self, status_str: str
    ) -> tuple[Optional[datetime], Optional[datetime]]:
        """Extrahuje začátek a konec aukce ze stringu."""
        if not status_str:
            return None, None

        match = re.search(
            r"\((\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})\s*-\s*(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})\)",
            status_str,
        )
        if match:
            start_str, end_str = match.groups()
            try:
                start_dt = datetime.strptime(start_str, "%d.%m.%Y %H:%M")
                end_dt = datetime.strptime(end_str, "%d.%m.%Y %H:%M")
                return start_dt, end_dt
            except ValueError:
                return None, None
        return None, None

    async def scrape(self, session: aiohttp.ClientSession) -> List[EstateSchema]:
        """Hlavní dech extraktoru. Iteruje přes vymezené formy hmoty."""
        logger.info(f"📡 {self.scraper_name}: Zahajuji extrakční cyklus...")
        valid_items: List[EstateSchema] = []

        # 10 = Pozemky, 11 = Stavby
        target_categories = ["10", "11"]

        for category_id in target_categories:
            page: int = 1
            logger.info(
                f"📡 {self.scraper_name}: Otevírám datový proud pro kategorii {category_id}..."
            )

            while True:
                payload = self._build_payload(page, category_id)
                headers = self.get_default_headers()
                headers["Content-Type"] = "application/json;charset=UTF-8"

                try:
                    async with session.post(
                        self.api_url, json=payload, headers=headers
                    ) as response:
                        response.raise_for_status()
                        data: Dict[str, Any] = await response.json()
                except aiohttp.ClientError as e:
                    logger.error(
                        f"Narušení toku na stránce {page} v kategorii {category_id}: {e}"
                    )
                    break

                raw_items: List[Dict[str, Any]] = data.get("Properties", [])

                if not raw_items:
                    logger.info(
                        f"{self.scraper_name}: Dosaženo prázdnoty na stránce {page} (Kategorie {category_id})."
                    )
                    break

                logger.info(
                    f"{self.scraper_name}: Zpracovávám {len(raw_items)} položek ze stránky {page} (Kategorie {category_id})."
                )

                for item in raw_items:
                    parsed_estate = self._parse_item(item, category_id)
                    # Geografický filtr propustí veškerou hmotu.
                    if parsed_estate:
                        valid_items.append(parsed_estate)

                page_count = data.get("PageCount", 0)
                if page >= page_count:
                    break

                page += 1

        return valid_items

    def _parse_item(self, raw_data: Dict[str, Any], category_id: str) -> Optional[EstateSchema]:
        """Transformuje fragment dat do našeho centrálního kontraktu."""
        try:
            item_id = str(raw_data["Id"])
            start_dt, end_dt = self._parse_dates(raw_data.get("StatusName", ""))
            seller = raw_data.get("Organization", {}).get("u04Name")

            # Exaktní určení typu na základě ID kategorie z API
            property_type = "Pozemky" if category_id == "10" else "Stavby"

            return EstateSchema(
                source_id=item_id,
                source_portal="nabidkamajetku.gov.cz",
                property_type=property_type,  # Mapování do schématu
                title=raw_data.get("Name", "Neznámý název"),
                starting_price=self._parse_price(raw_data.get("Price")),
                estimated_price=None,
                location_region=None,
                location_district=raw_data.get("DistrictName"),
                location_city=None,
                cadastral_area=None,
                auction_start=start_dt,
                auction_end=end_dt,
                seller_institution=seller,
                url=f"https://nabidkamajetku.gov.cz/Home/Detail/{item_id}",
                area_m2=None,
            )
        except KeyError as e:
            logger.warning(
                f"Chybějící esenciální klíč {e} u záznamu {raw_data.get('Id')}"
            )
            return None
        except Exception as e:
            logger.warning(f"Chyba transformace záznamu {raw_data.get('Id')}: {e}")
            return None
