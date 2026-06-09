from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, ConfigDict


class EstateSchema(BaseModel):
    """
    Centrální datový kontrakt pro prodej státního a lesního majetku.
    Každý extraktor transformuje surová data do této podoby.
    """
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

    # 1. Identifikace
    source_id: str = Field(
        ...,
        description="Unikátní identifikátor v rámci zdrojového portálu."
    )
    source_portal: str = Field(
        ...,
        description="Původ dat (např. 'portaldrazeb.cz', 'nabidkamajetku.gov.cz')."
    )
    property_type: Optional[str] = Field(
        None,
        description="Základní klasifikace hmoty (např. 'Pozemky' nebo 'Stavby'). U neznámých zdrojů může být dočasně None.",
    )
    title: str = Field(
        ...,
        description="Hlavní název nebo stručný popis nemovitosti."
    )
    description: Optional[str] = Field(
        None, description="Detailní textový popis nemovitosti z hloubkového průzkumu."
    )

    # 2. Finanční osa
    starting_price: Optional[float] = Field(
        None,
        description="Vyvolávací nebo požadovaná cena v CZK."
    )
    estimated_price: Optional[float] = Field(
        None,
        description="Odhadní cena v CZK (pokud je k dispozici)."
    )

    # 3. Geografické ukotvení
    location_region: Optional[str] = Field(
        None,
        description="Kraj (např. 'Středočeský kraj')."
    )
    location_district: Optional[str] = Field(
        None,
        description="Okres (např. 'Příbram')."
    )
    location_city: Optional[str] = Field(
        None,
        description="Město nebo obec."
    )
    cadastral_area: Optional[str] = Field(
        None,
        description="Katastrální území."
    )

    # 4. Časová osa
    auction_start: Optional[datetime] = Field(
        None,
        description="Datum a čas začátku dražby/prodeje."
    )
    auction_end: Optional[datetime] = Field(
        None,
        description="Datum a čas konce dražby/prodeje."
    )

    # 5. Původ a navigace
    seller_institution: Optional[str] = Field(
        None,
        description="Instituce, která majetek nabízí (např. 'ÚZSVM', 'Lesy ČR')."
    )
    url: HttpUrl = Field(
        ...,
        description="Přímý odkaz na detail nabídky."
    )

    # 6. Fyzické parametry
    area_m2: Optional[float] = Field(
        None,
        description="Plocha pozemku v metrech čtverečních."
    )

    @property
    def is_active(self) -> bool:
        """Určuje, zda je nabídka časově platná vzhledem k aktuálnímu okamžiku."""
        if self.auction_end is None:
            return True
        return datetime.now() <= self.auction_end