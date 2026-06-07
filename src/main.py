import asyncio
import json
import logging
from typing import List

import aiohttp

from src.extract.lesy_cr import LesyCrScraper
from src.extract.nabidka_majetku import NabidkaMajetkuScraper
from src.extract.portal_drazeb import PortalDrazebScraper
from src.schemas.estate import EstateSchema

# Konfigurace centrálního logování
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def run_pipeline() -> None:
    """Řídí asynchronní spuštění všech extraktorů a agregaci dat."""

    # Inicializace instancí jednotlivých extraktorů
    scrapers = [PortalDrazebScraper(), NabidkaMajetkuScraper(), LesyCrScraper()]

    logger.info("Zahajuji ETL pipeline: Fáze Extrakce.")

    aggregated_estates: List[EstateSchema] = []

    # Otevření sdíleného asynchronního spojení pro všechny extraktory
    # Použití jedné session je best practice pro efektivní správu TCP konekcí
    async with aiohttp.ClientSession() as session:
        # Vytvoření seznamu korutin (úloh) pro paralelní běh
        tasks = [scraper.scrape(session) for scraper in scrapers]

        # Spuštění všech úloh současně a čekání na jejich dokončení
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Agregace výsledků z jednotlivých extraktorů do jednoho toku
        for scraper_result in results:
            if isinstance(scraper_result, Exception):
                logger.error(f"Kritická chyba v extraktoru: {scraper_result}")
            elif isinstance(scraper_result, list):
                aggregated_estates.extend(scraper_result)

    total_items = len(aggregated_estates)
    logger.info(f"Fáze Extrakce dokončena. Celkem získáno: {total_items} záznamů.")

    # Serializace datové hmoty pro ověření (Pydantic V2 automaticky řeší datetime)
    output_file = "raw_estates_dump.json"
    with open(output_file, "w", encoding="utf-8") as f:
        # Pydantic model_dump(mode='json') zajistí bezpečný převod do JSON kompatibilních typů
        json_data = [estate.model_dump(mode="json") for estate in aggregated_estates]
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    logger.info(f"Data ukotvena v souboru: {output_file}")


def main() -> None:
    """Spouštěcí bod aplikační smyčky."""
    try:
        asyncio.run(run_pipeline())
    except KeyboardInterrupt:
        logger.info("Proces byl manuálně přerušen.")
    except Exception as e:
        logger.critical(f"Fatální selhání pipeline: {e}", exc_info=True)


if __name__ == "__main__":
    main()
