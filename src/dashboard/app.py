import pandas as pd
import streamlit as st
from sqlmodel import Session, create_engine, select

from src.models.estate import Estate

# Nastavení struktury a chování prostoru
st.set_page_config(
    page_title="State Real Estate Watchdog", page_icon="👁️", layout="wide"
)

# Inicializace spojení s pamětí
SQLITE_URL = "sqlite:///estates.db"
engine = create_engine(SQLITE_URL, echo=False)


@st.cache_data(ttl=3600)
def load_data() -> pd.DataFrame:
    """Extrahuje čistou hmotu z databáze bez další transformace."""
    with Session(engine) as session:
        statement = select(Estate)
        results = session.exec(statement).all()
        df = pd.DataFrame([r.model_dump() for r in results])
        return df


def main() -> None:
    st.title("👁️ State Real Estate Watchdog")
    st.markdown("Holistický přehled o pohybu státního a lesního majetku v prostoru.")

    df = load_data()

    if df.empty:
        st.warning("Paměť je prázdná. Proveď nejprve extrakci dat.")
        return

    # Postavení filtrů (Rozdělení zorného pole)
    st.sidebar.header("Filtry Prostoru a Energie")

    portals = st.sidebar.multiselect(
        "Zdrojový pramen", sorted(df["source_portal"].dropna().unique())
    )

    # Filtr čerpající typy přímo z databázového sloupce property_type
    available_types = df["property_type"].dropna().unique()
    property_types = st.sidebar.multiselect(
        "Typ nemovitosti",
        options=sorted(available_types),
        default=sorted(available_types),
    )

    regions = st.sidebar.multiselect(
        "Kraj", sorted(df["location_region"].dropna().unique())
    )

    # Dynamický filtr pro okresy na základě vybraného kraje
    available_districts = df["location_district"].dropna().unique()
    if regions:
        available_districts = (
            df[df["location_region"].isin(regions)]["location_district"]
            .dropna()
            .unique()
        )
    districts = st.sidebar.multiselect("Okres", sorted(available_districts))

    # Aplikace záměru (Filtrování)
    filtered_df = df.copy()
    if portals:
        filtered_df = filtered_df[filtered_df["source_portal"].isin(portals)]
    if property_types:
        filtered_df = filtered_df[filtered_df["property_type"].isin(property_types)]
    if regions:
        filtered_df = filtered_df[filtered_df["location_region"].isin(regions)]
    if districts:
        filtered_df = filtered_df[filtered_df["location_district"].isin(districts)]

    # Vizualizace základních metrik
    col1, col2, col3 = st.columns(3)
    col1.metric("Aktivní inzeráty", len(filtered_df))
    col2.metric(
        "Celková vyvolávací cena",
        f"{filtered_df['starting_price'].sum():,.0f} Kč".replace(",", " "),
    )

    avg_price_m2 = filtered_df["price_per_m2"].mean()
    col3.metric(
        "Průměrná cena za m²",
        f"{avg_price_m2:,.0f} Kč".replace(",", " ")
        if pd.notnull(avg_price_m2)
        else "N/A",
    )

    st.divider()

    # Zhmotnění tabulky
    st.dataframe(
        filtered_df[
            [
                "title",
                "source_portal",
                "property_type",
                "location_district",
                "starting_price",
                "area_m2",
                "price_per_m2",
                "auction_end",
                "url",
            ]
        ],
        use_container_width=True,
        column_config={
            "title": st.column_config.TextColumn("Název nemovitosti"),
            "source_portal": st.column_config.TextColumn("Zdroj"),
            "property_type": st.column_config.TextColumn("Typ"),
            "location_district": st.column_config.TextColumn("Okres"),
            "url": st.column_config.LinkColumn("Odkaz na zdroj"),
            "starting_price": st.column_config.NumberColumn("Cena (Kč)", format="%d"),
            "price_per_m2": st.column_config.NumberColumn(
                "Cena za m² (Kč)", format="%d"
            ),
            "area_m2": st.column_config.NumberColumn("Plocha (m²)", format="%d"),
        },
    )


if __name__ == "__main__":
    main()
