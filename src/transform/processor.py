import logging
from pathlib import Path

import polars as pl
from sqlmodel import Session, SQLModel, create_engine, select

from src.models.estate import Estate

logger = logging.getLogger(__name__)


class DataTransformer:
    """
    Purifikační vrstva ETL pipeline postavená na Polars a SQLModel.
    Zpracovává celou ČR bez geografického omezení a ukládá hmotu do SQLite.
    """

    def __init__(
        self, input_file: str = "raw_estates_dump.json", db_file: str = "estates.db"
    ):
        self.input_path = Path(input_file)
        self.sqlite_url = f"sqlite:///{db_file}"
        self.engine = create_engine(self.sqlite_url, echo=False)

        # Inicializace schématu v realitě databáze
        SQLModel.metadata.create_all(self.engine)

    def process(self) -> None:
        if not self.input_path.exists():
            logger.error(f"Zdrojový soubor {self.input_path} neexistuje.")
            return

        logger.info("Zahajuji transformaci celé ČR pomocí Polars...")

        schema_overrides = {
            "source_id": pl.String,
            "source_portal": pl.String,
            "property_type": pl.String,  # Přidáno do Polars schématu
            "title": pl.String,
            "starting_price": pl.Float64,
            "estimated_price": pl.Float64,
            "location_region": pl.String,
            "location_district": pl.String,
            "location_city": pl.String,
            "cadastral_area": pl.String,
            "auction_start": pl.String,
            "auction_end": pl.String,
            "seller_institution": pl.String,
            "url": pl.String,
            "area_m2": pl.Float64,
        }

        df = pl.read_json(self.input_path, schema_overrides=schema_overrides)

        # Líná transformace
        q = (
            df.lazy()
            .unique(subset=["source_portal", "source_id"])
            .with_columns(
                # Inteligentní doplňování chybějících typů (pro Portál dražeb)
                pl.when(pl.col("property_type").is_null())
                .then(
                    pl.when(
                        pl.col("title").str.contains(
                            r"(?i)dům|budova|stavba|objekt|garáž|byt|jednotka|chata|chalupa|stavení|hala|sklad"
                        )
                    )
                    .then(pl.lit("Stavby"))
                    .otherwise(pl.lit("Pozemky"))
                )
                .otherwise(pl.col("property_type"))
                .alias("property_type"),
                # Výpočet ceny za m2
                pl.when(
                    pl.col("area_m2").is_not_null()
                    & (pl.col("area_m2") > 0)
                    & pl.col("starting_price").is_not_null()
                )
                .then(pl.col("starting_price") / pl.col("area_m2"))
                .otherwise(None)
                .round(2)
                .alias("price_per_m2"),
                # Konverze DateTime
                pl.col("auction_start").str.strptime(
                    pl.Datetime, format="%Y-%m-%dT%H:%M:%S", strict=False
                ),
                pl.col("auction_end").str.strptime(
                    pl.Datetime, format="%Y-%m-%dT%H:%M:%S", strict=False
                ),
            )
        )

        clean_df = q.collect()
        logger.info(
            f"Po prostorové deduplikaci zbývá {clean_df.height} čistých záznamů."
        )

        self._upsert_to_db(clean_df)

    def _upsert_to_db(self, df: pl.DataFrame) -> None:
        """Inteligentní uložení hmoty (Upsert). Existující záznamy aktualizuje, nové vkládá."""
        logger.info("Ukotvuji data v relační paměti (SQLite)...")
        records = df.to_dicts()
        inserted = 0
        updated = 0

        with Session(self.engine) as session:
            for record in records:
                # Pokus o nalezení existující energie podle přirozeného klíče
                statement = select(Estate).where(
                    Estate.source_portal == record["source_portal"],
                    Estate.source_id == record["source_id"],
                )
                existing_estate = session.exec(statement).first()

                if existing_estate:
                    # Aktualizace existující hmoty
                    for key, value in record.items():
                        setattr(existing_estate, key, value)
                    session.add(existing_estate)
                    updated += 1
                else:
                    # Vložení nové hmoty
                    new_estate = Estate(**record)
                    session.add(new_estate)
                    inserted += 1

            session.commit()

        logger.info(
            f"Ukotvení dokončeno: {inserted} nových, {updated} aktualizovaných záznamů."
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    transformer = DataTransformer()
    transformer.process()
