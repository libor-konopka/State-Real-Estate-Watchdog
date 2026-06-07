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
    """

    def __init__(self) -> None:
        super().__init__()
        self.api_url: str = "https://nabidkamajetku.gov.cz/api/Property/List"
        self.page_size: int = 25
        # Byznysové ohraničení toku - sledujeme pouze tyto okresy
        self.target_districts = {
            "Benešov", "Beroun", "Kutná Hora", "Mladá Boleslav",
            "Praha-východ", "Praha-západ", "Příbram"
        }

    def _build_payload(self, page: int) -> Dict[str, Any]:
        """Konstruuje datový záměr. CategoryId 11 odpovídá filtru na 'Nemovitosti'."""
        return {
            "ListType": "all",
            "Page": page,
            "PageSize": self.page_size,
            "Order": "Default",
            "OrderDesc": "true",
            "CategoryId": "11",
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
            "State": "0"
        }

    def _parse_price(self, price_str: Optional[str]) -> Optional[float]:
        """Očistí textovou strukturu ('3 621 888,00') a přetaví ji na desetinné číslo."""
        if not price_str:
            return None
        try:
            # Odstranění běžných mezer, nezlomitelných mezer a převod čárky na tečku
            clean_str = price_str.replace(" ", "").replace("\xa0", "").replace(",", ".")
            return float(clean_str)
        except ValueError:
            return None

    def _parse_dates(self, status_str: str) -> tuple[Optional[datetime], Optional[datetime]]:
        """Extrahuje začátek a konec aukce ze stringu typu 'Aukce vyhlášena (16.06.2026 11:00 - 17.06.2026 11:00)'."""
        if not status_str:
            return None, None

        # Regulární výraz zachytí dva bloky s datem a časem
        match = re.search(r"\((\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})\s*-\s*(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})\)", status_str)
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
        """Hlavní dech extraktoru."""
        logger.info(f"📡 {self.scraper_name}: Zahajuji extrakční cyklus...")
        valid_items: List[EstateSchema] = []
        page: int = 1

        while True:
            payload = self._build_payload(page)
            headers = self.get_default_headers()
            # U .NET API je dobré explicitně potvrdit typ odesílané hmoty
            headers["Content-Type"] = "application/json;charset=UTF-8"

            try:
                async with session.post(self.api_url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    data: Dict[str, Any] = await response.json()
            except aiohttp.ClientError as e:
                logger.error(f"Narušení toku na stránce {page}: {e}")
                break

            raw_items: List[Dict[str, Any]] = data.get("Properties", [])

            if not raw_items:
                logger.info(f"{self.scraper_name}: Dosaženo prázdnoty na stránce {page}. Konec cyklu.")
                break

            logger.info(f"{self.scraper_name}: Zpracovávám {len(raw_items)} položek ze stránky {page}.")

            for item in raw_items:
                parsed_estate = self._parse_item(item)
                if parsed_estate:
                    # Architektonická filtrace naší sledované zóny
                    if parsed_estate.location_district in self.target_districts:
                        valid_items.append(parsed_estate)

            # API nám prozrazuje celkový počet stránek. Můžeme cyklus elegantně ukončit.
            page_count = data.get("PageCount", 0)
            if page >= page_count:
                break

            page += 1

        return valid_items

    def _parse_item(self, raw_data: Dict[str, Any]) -> Optional[EstateSchema]:
        """Transformuje fragment dat do našeho centrálního kontraktu."""
        try:
            item_id = str(raw_data["Id"])

            # Bezpečná extrakce složitějších uzlů
            start_dt, end_dt = self._parse_dates(raw_data.get("StatusName", ""))
            seller = raw_data.get("Organization", {}).get("u04Name")

            return EstateSchema(
                source_id=item_id,
                source_portal="nabidkamajetku.gov.cz",
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
                area_m2=None
            )
        except KeyError as e:
            logger.warning(f"Chybějící esenciální klíč {e} u záznamu {raw_data.get('Id')}")
            return None
        except Exception as e:
            logger.warning(f"Chyba transformace záznamu {raw_data.get('Id')}: {e}")
            return None