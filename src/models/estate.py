from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Estate(SQLModel, table=True):
    """
    Fyzické ukotvení inzerátu v paměti databáze.
    Využívá složený unikátní index pro Upsert (ochrana proti duplicitám).
    """

    # Systémový primární klíč
    id: Optional[int] = Field(default=None, primary_key=True)

    # Složený přirozený klíč (Zdroj + ID na zdroji)
    source_portal: str = Field(index=True)
    source_id: str = Field(index=True)

    property_type: str = Field(index=True)  # "Pozemky" / "Stavby"

    title: str
    description: Optional[str] = None
    starting_price: Optional[float] = None
    estimated_price: Optional[float] = None
    price_per_m2: Optional[float] = None  # Vypočtená metrika

    location_region: Optional[str] = Field(default=None, index=True)
    location_district: Optional[str] = Field(default=None, index=True)
    location_city: Optional[str] = None
    cadastral_area: Optional[str] = None

    area_m2: Optional[float] = None

    auction_start: Optional[datetime] = None
    auction_end: Optional[datetime] = None

    seller_institution: Optional[str] = None
    url: str

    # Přidání meta pole pro sledování času záchytu (volitelné, ale užitečné pro watchdog)
    captured_at: datetime = Field(default_factory=datetime.utcnow)
