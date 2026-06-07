import logging
from abc import ABC, abstractmethod
from typing import List

import aiohttp

from src.schemas.estate import EstateSchema

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    Fundamentální archetyp pro všechny extraktory v systému.
    Garantuje jednotné rozhraní (polymorfismus) pro hlavní ETL cyklus.
    """

    def __init__(self) -> None:
        # Automatické ukotvení názvu konkrétního extraktoru pro přesnější logging
        self.scraper_name: str = self.__class__.__name__

    @abstractmethod
    async def scrape(self, session: aiohttp.ClientSession) -> List[EstateSchema]:
        """
        Hlavní asynchronní cyklus (dech) extraktoru.

        Tuto metodu musí implementovat každý potomek. Přijímá otevřené
        spojení (session) a musí vrátit striktně validovaný seznam nemovitostí.
        """
        pass

    def get_default_headers(self) -> dict[str, str]:
        """
        Poskytuje základní mimikry pro splynutí s běžným síťovým tokem.
        Potomci mohou tuto metodu přepsat nebo rozšířit.
        """
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "cs-CZ,cs;q=0.9",
        }