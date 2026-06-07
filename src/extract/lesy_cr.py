import logging
import re
from datetime import datetime
from typing import List, Optional

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from src.extract.base import BaseScraper
from src.schemas.estate import EstateSchema

logger = logging.getLogger(__name__)


class LesyCrScraper(BaseScraper):
    """
    Asynchronní extraktor pro pnm.lesycr.cz.
    Využívá headless prohlížeč pro manipulaci s APEX reportem,
    filtruje živé záznamy a iteruje skrze stránky.
    """

    def __init__(self) -> None:
        super().__init__()
        self.base_url = "https://pnm.lesycr.cz/apex/f?p=175:7:0"

    def _parse_price(self, price_str: str) -> Optional[float]:
        if not price_str or price_str.strip() == "":
            return None
        try:
            return float(price_str.replace(".", "").replace(" ", "").strip())
        except ValueError:
            return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        if not date_str or date_str.strip() == "":
            return None
        try:
            return datetime.strptime(date_str.strip(), "%d.%m.%Y")
        except ValueError:
            return None

    def _parse_id_from_url(self, link: str) -> Optional[str]:
        match = re.search(r"P13_ID_MAJ:(\d+)", link)
        if match:
            return match.group(1)
        return None

    def _parse_page_content(self, html_content: str) -> List[EstateSchema]:
        """Těží datovou hmotu z aktuálně zobrazeného DOMu s defenzivní filtrací."""
        items: List[EstateSchema] = []
        soup = BeautifulSoup(html_content, "html.parser")
        rows = soup.find_all("tr")

        for row in rows:
            link_cell = row.find("td", headers="LINK")
            if not link_cell:
                continue

            a_tag = link_cell.find("a")
            if not a_tag or not a_tag.get("href"):
                continue

            href = a_tag["href"]
            item_id = self._parse_id_from_url(href)
            if not item_id:
                continue

            try:
                # Kontrola typu (pouze Prodej)
                type_cell = row.find("td", headers="C288994971869363934")
                offer_type = type_cell.text.strip() if type_cell else ""
                if "Prodej" not in offer_type:
                    continue

                # Kontrola stavu (pouze živé nabídky)
                status_cell = row.find("td", headers="C182519181887705490")
                status = status_cell.text.strip() if status_cell else ""
                if "Vypsané" not in status:
                    continue

                title_cell = row.find("td", headers="C326410314433328373")
                title = title_cell.text.strip() if title_cell else "Neznámý název"

                price_cell = row.find("td", headers="C326411100233328374")
                price_str = price_cell.text.strip() if price_cell else ""

                date_cell = row.find("td", headers="C326413850831328375")
                date_str = date_cell.text.strip() if date_cell else ""

                region_cell = row.find("td", headers="C326411539589328374")
                region = region_cell.text.strip() if region_cell else None

                district_cell = row.find("td", headers="C326411886832328374")
                district = district_cell.text.strip() if district_cell else None

                area_cell = row.find("td", headers="C326418281440328383")
                area_m2_str = area_cell.text.strip() if area_cell else None
                area_m2 = (
                    float(area_m2_str)
                    if area_m2_str and area_m2_str.isdigit()
                    else None
                )

                cadastral_cell = row.find("td", headers="C326431899615328393")
                cadastral_area = cadastral_cell.text.strip() if cadastral_cell else None

                estate = EstateSchema(
                    source_id=item_id,
                    source_portal="pnm.lesycr.cz",
                    title=title,
                    starting_price=self._parse_price(price_str),
                    estimated_price=None,
                    location_region=region,
                    location_district=district,
                    location_city=None,
                    cadastral_area=cadastral_area,
                    auction_start=None,
                    auction_end=self._parse_date(date_str),
                    seller_institution="Lesy ČR",
                    url=f"https://pnm.lesycr.cz/apex/{href}",
                    area_m2=area_m2,
                )
                items.append(estate)

            except Exception as e:
                logger.warning(f"Odchylka při transformaci položky {item_id}: {e}")
                continue

        return items

    async def scrape(self, session: aiohttp.ClientSession) -> List[EstateSchema]:
        """Aktivuje prohlížeč, vnutí filtry do UI a provede rychlou extrakci platných záznamů."""
        logger.info(f"📡 {self.scraper_name}: Zhmotňuji headless prohlížeč pro APEX...")
        valid_items: List[EstateSchema] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.get_default_headers()["User-Agent"]
            )
            page = await context.new_page()

            try:
                await page.goto(self.base_url, wait_until="networkidle")
                await page.wait_for_selector("table.a-IRR-table", timeout=15000)

                # Vynucení filtrace přes APEX UI
                logger.info(
                    f"📡 {self.scraper_name}: Aplikuji filtr na živé záznamy ('Vypsané')..."
                )
                search_input = page.locator(".a-IRR-search-field")
                search_button = page.locator(".a-IRR-button--search")

                if await search_input.count() > 0 and await search_button.count() > 0:
                    await search_input.fill("Vypsané")
                    await search_button.click()
                    # Vyčkání na překreslení tabulky a ustálení sítě po filtraci
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(2000)
                else:
                    logger.warning(
                        f"⚠️ {self.scraper_name}: Nenašel jsem pole pro filtr. Pokračuji bez něj."
                    )

                # Krátký iterativní cyklus přes profiltrovaný obsah
                page_num = 1
                while True:
                    await page.wait_for_selector("table.a-IRR-table", timeout=15000)
                    html_content = await page.content()

                    new_items = self._parse_page_content(html_content)
                    valid_items.extend(new_items)
                    logger.info(
                        f"{self.scraper_name}: Extrahováno {len(new_items)} platných položek ze stránky {page_num}."
                    )

                    next_button = page.locator(
                        "button.a-IRR-button--pagination:has(.icon-right-chevron)"
                    )

                    if (
                        await next_button.count() > 0
                        and not await next_button.is_disabled()
                    ):
                        await next_button.click()
                        await page.wait_for_load_state("networkidle")
                        await page.wait_for_timeout(1000)  # Necháme DOM nadechnout
                        page_num += 1
                    else:
                        logger.info(
                            f"{self.scraper_name}: Dosaženo konce filtrovaného pramene."
                        )
                        break

            except Exception as e:
                logger.error(f"Kritické narušení toku APEXu: {e}")
            finally:
                await browser.close()

        return valid_items
