import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from src.extract.base import BaseScraper
from src.schemas.estate import EstateSchema

logger = logging.getLogger(__name__)


class LesyCrScraper(BaseScraper):
    """
    Asynchronní extraktor pro pnm.lesycr.cz (Strana 7).
    Aplikuje UI filtr a využívá relativní kotevní strategii pro maximální odolnost
    vůči strukturálním změnám APEX tabulek.
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
        match = re.search(r"ID_MAJ:(\d+)", link)
        if match:
            return match.group(1)
        return None

    def _parse_page_content(self, html_content: str) -> List[EstateSchema]:
        """Těží data pomocí precizního kotevního bodu, eliminuje historický šum i falešné shody."""
        items: List[EstateSchema] = []
        soup = BeautifulSoup(html_content, "html.parser")

        rows = soup.find_all("tr")
        for row in rows:
            # 1. Detekce platného uzlu
            a_tag = row.find("a", href=re.compile(r"ID_MAJ:(\d+)"))
            if not a_tag:
                continue

            href = a_tag["href"]
            item_id = self._parse_id_from_url(href)
            if not item_id:
                continue

            try:
                cells = row.find_all("td")

                # 2. Precizní ukotvení: Hledáme buňku, která je EXACTNĚ slovem 'Prodej'
                anchor_idx = -1
                for i, cell in enumerate(cells):
                    cell_text = cell.get_text(strip=True)
                    if cell_text == "Prodej":
                        anchor_idx = i
                        break

                # Zvýšení ochranné hranice na 8.
                # Pokud extrahujeme 8 prvků vlevo od kotvy, pole musí být dostatečně hluboké.
                if anchor_idx < 8:
                    continue

                # 3. Relativní extrakce parametrů vůči kotvě
                # POZOR: Indexy musíš zkalibrovat podle skutečného pořadí sloupců na webu.
                # Předpokládám, že Kategorie (-7) je mezi Názvem (-8) a Cenou (-6).
                title = cells[anchor_idx - 8].text.strip()
                raw_kategorie = cells[anchor_idx - 7].text.strip()
                price_str = cells[anchor_idx - 6].text.strip()
                date_str = cells[anchor_idx - 5].text.strip()
                region = cells[anchor_idx - 4].text.strip()
                district = cells[anchor_idx - 3].text.strip()

                area_m2_str = cells[anchor_idx - 2].text.strip()
                area_m2_str = "".join(filter(str.isdigit, area_m2_str))
                area_m2 = float(area_m2_str) if area_m2_str else None

                cadastral_area = cells[anchor_idx - 1].text.strip()

                # Pythonic klasifikace (Ternární operátor).
                # Cokoliv co není exaktně "Pozemky", propadá do "Stavby".
                property_type = "Pozemky" if raw_kategorie == "Pozemky" else "Stavby"

                estate = EstateSchema(
                    source_id=item_id,
                    source_portal="pnm.lesycr.cz",
                    property_type=property_type,
                    title=title or "Neznámý název",
                    starting_price=self._parse_price(price_str),
                    estimated_price=None,
                    location_region=region or None,
                    location_district=district or None,
                    location_city=None,
                    cadastral_area=cadastral_area or None,
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
        """Aktivuje prohlížeč, vynucuje UI filtr a provádí asynchronní iteraci s přísnou kontrolou mutací DOMu."""
        logger.info(
            f"📡 {self.scraper_name}: Zhmotňuji headless prohlížeč pro stranu 7..."
        )
        valid_items: List[EstateSchema] = []
        seen_ids = (
            set()
        )  # Ochrana proti zachycení stejných dat (tzv. "ghost" řádky při rychlém čtení)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.get_default_headers()["User-Agent"]
            )
            page = await context.new_page()

            try:
                await page.goto(self.base_url, wait_until="networkidle")
                await page.wait_for_selector("table.a-IRR-table", timeout=15000)

                logger.info(
                    f"📡 {self.scraper_name}: Zadávám omezující filtr 'Vypsané'..."
                )
                search_input = page.locator(".a-IRR-search-field")
                search_button = page.locator(".a-IRR-button--search")

                if await search_input.count() > 0 and await search_button.count() > 0:
                    await search_input.fill("Vypsané")
                    await search_button.click()
                    # Zvýšený timeout po filtru pro zajištění prvotního renderu
                    await page.wait_for_load_state("networkidle")
                    await page.wait_for_timeout(3000)
                else:
                    logger.warning(
                        f"⚠️ {self.scraper_name}: Vyhledávací rozhraní nenalezeno."
                    )

                page_num = 1
                while True:
                    # Počkáme, až se objeví alespoň jeden odkaz s ID_MAJ (důkaz datové přítomnosti)
                    try:
                        await page.wait_for_selector(
                            'table.a-IRR-table a[href*="ID_MAJ"]', timeout=15000
                        )
                    except Exception:
                        logger.warning(
                            f"⚠️ {self.scraper_name}: Nenašel jsem žádná data na stránce {page_num}."
                        )
                        break

                    html_content = await page.content()

                    new_items = self._parse_page_content(html_content)

                    # Deduplikace na úrovni čtení (pokud AJAX nestihl překreslit, ignorujeme)
                    unique_new_items = []
                    for item in new_items:
                        if item.source_id not in seen_ids:
                            seen_ids.add(item.source_id)
                            unique_new_items.append(item)

                    valid_items.extend(unique_new_items)
                    logger.info(
                        f"{self.scraper_name}: Ze stránky {page_num} extrahováno {len(unique_new_items)} unikátních platných položek (z {len(new_items)} načtených)."
                    )

                    next_button = page.locator(
                        "button.a-IRR-button--pagination:has(.icon-right-chevron)"
                    ).first

                    if (
                        await next_button.count() > 0
                        and not await next_button.is_disabled()
                    ):
                        # Klikneme a explicitně počkáme na AJAXovou "točící se" ikonu, nebo alespoň dostatečně dlouho
                        await next_button.evaluate("node => node.click()")
                        await page.wait_for_load_state("networkidle")

                        # ČEKACÍ SMYČKA: Vynutíme čekání na změnu (3 vteřiny by měly na APEX stačit)
                        logger.debug(
                            f"{self.scraper_name}: Čekám na synchronizaci DOMu..."
                        )
                        await page.wait_for_timeout(3000)

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
