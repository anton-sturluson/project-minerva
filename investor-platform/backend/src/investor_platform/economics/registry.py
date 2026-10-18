"""Authoritative definitions and publication schedules for economics data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    """Publisher definition, kept in code rather than duplicate database records."""

    id: str
    name: str
    url: str
    publication_frequency: str
    publication_schedule: str
    polling_frequency: str
    cadence_url: str
    enabled: bool = True
    disabled_reason: str | None = None


@dataclass(frozen=True)
class Series:
    """One stable measurement definition with units and interpretation."""

    key: str
    source_id: str
    name: str
    unit: str
    frequency: str
    description: str
    source_url: str
    source_key: str
    methodology_notes: str = ""


SOURCES: tuple[Source, ...] = (
    Source(
        "bls",
        "BLS",
        "https://www.bls.gov/cpi/data.htm",
        "Monthly",
        "Published with CPI at 08:30 ET; calendar dates vary. See the publisher release calendar.",
        "Weekdays at 09:00 ET; current and prior year, plus initial history",
        "https://www.bls.gov/schedule/news_release/cpi.htm",
    ),
    Source(
        "usda",
        "USDA",
        "https://www.fns.usda.gov/research/cnpp/usda-food-plans/cost-food-monthly-reports",
        "Monthly",
        "Monthly food-plan report; no fixed release day confirmed.",
        "Weekdays at 14:00 ET",
        "https://www.fns.usda.gov/research/cnpp/usda-food-plans/cost-food-monthly-reports",
    ),
    Source(
        "eia",
        "EIA",
        "https://www.eia.gov/petroleum/gasdiesel/",
        "Weekly",
        "Tuesday about 10:00 ET; Wednesday after federal holidays; Monday observations.",
        "Tuesday and Wednesday at 10:30 ET",
        "https://www.eia.gov/petroleum/gasdiesel/schedule.php",
    ),
    Source(
        "fidelity",
        "Fidelity",
        "https://about.fidelity.com/data-and-insights",
        "Quarterly",
        "Quarterly retirement analysis; no fixed release date confirmed.",
        "Disabled",
        "https://about.fidelity.com/data-and-insights",
        False,
        "Automated access and redistribution require a permitted route.",
    ),
    Source(
        "redfin",
        "Redfin",
        "https://www.redfin.com/news/data-center/",
        "Quarterly",
        "Quarterly tracker updates with monthly observations; exact WSJ feed unresolved.",
        "Disabled",
        "https://www.redfin.com/news/data-center/",
        False,
        "Exact comparable mortgage-payment feed has not been verified.",
    ),
    Source(
        "edmunds",
        "Edmunds",
        "https://www.edmunds.com/insights/",
        "Unknown / irregular",
        "Monthly transaction-price observations; publication schedule unconfirmed.",
        "Disabled",
        "https://help.edmunds.com/hc/en-us/articles/206103257-Accessing-Edmunds-data",
        False,
        "Public API closed; matching complete monthly feed unavailable.",
    ),
    Source(
        "opis",
        "OPIS",
        "https://www.opis.com/",
        "Daily",
        "Daily retail fuel pricing product; delivery depends on subscription.",
        "Disabled",
        "https://www.opis.com/product/pricing/oil-prices-forecast-and-history/",
        False,
        "Licensed feed required. EIA weekly data is a clearly labelled alternative.",
    ),
    Source(
        "factset",
        "FactSet",
        "https://www.factset.com/",
        "Daily trading observations",
        "Market data update timing depends on the entitled product.",
        "Disabled",
        "https://www.factset.com/",
        False,
        "Exact entitled stock-price feed not configured.",
    ),
)

BLS_URL: str = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
USDA_URL: str = "https://fns-prod.azureedge.us/sites/default/files/resource-files/usdamoderatecostplan-sept2007-present.xlsx"
BLS_NOTE: str = (
    "U.S. city average, not seasonally adjusted. Sample and product mix can change; "
    "these price levels are not CPI inflation measures. BLS cannot vouch for the data "
    "or analyses derived from these data after the data have been retrieved from BLS."
)
SERIES: tuple[Series, ...] = (
    Series(
        "chicken-breast",
        "bls",
        "Boneless chicken breast",
        "USD/lb",
        "Monthly",
        "U.S. city average retail price",
        "https://data.bls.gov/timeseries/APU0000FF1101",
        "APU0000FF1101",
        BLS_NOTE,
    ),
    Series(
        "ground-beef",
        "bls",
        "Ground beef, 100% beef",
        "USD/lb",
        "Monthly",
        "U.S. city average retail price",
        "https://data.bls.gov/timeseries/APU0000703112",
        "APU0000703112",
        BLS_NOTE,
    ),
    Series(
        "eggs",
        "bls",
        "Eggs, grade A, large",
        "USD/dozen",
        "Monthly",
        "U.S. city average retail price",
        "https://data.bls.gov/timeseries/APU0000708111",
        "APU0000708111",
        BLS_NOTE,
    ),
    Series(
        "milk",
        "bls",
        "Whole fortified milk",
        "USD/gallon",
        "Monthly",
        "U.S. city average retail price",
        "https://data.bls.gov/timeseries/APU0000709112",
        "APU0000709112",
        BLS_NOTE,
    ),
    Series(
        "bread",
        "bls",
        "White pan bread",
        "USD/lb",
        "Monthly",
        "U.S. city average retail price",
        "https://data.bls.gov/timeseries/APU0000702111",
        "APU0000702111",
        BLS_NOTE,
    ),
    Series(
        "family-groceries",
        "usda",
        "Family grocery budget",
        "USD/week",
        "Monthly",
        "Moderate-cost plan: male and female 19–50, children 6–8 and 9–11",
        USDA_URL,
        "moderate-family-four",
        "Platform calculation: sum four USDA individual weekly costs. Basket methods "
        "change over time; this is not confirmed as the exact WSJ household.",
    ),
    Series(
        "gasoline",
        "eia",
        "Regular gasoline",
        "USD/gallon",
        "Weekly",
        "U.S. regular, all formulations, retail cash price including taxes",
        "https://www.eia.gov/dnav/pet/hist_xls/EMM_EPMR_PTE_NUS_DPGw.xls",
        "EMM_EPMR_PTE_NUS_DPG",
        "Weekly alternative to WSJ's daily OPIS series. "
        "Monday survey; methodology changed May 14, 2018.",
    ),
    Series(
        "diesel",
        "eia",
        "On-highway diesel",
        "USD/gallon",
        "Weekly",
        "Contiguous U.S. No. 2 on-highway diesel cash price including taxes",
        "https://www.eia.gov/dnav/pet/hist_xls/EMD_EPD2D_PTE_NUS_DPGw.xls",
        "EMD_EPD2D_PTE_NUS_DPG",
        "Weekly alternative to WSJ's daily OPIS series. "
        "Monday survey; methodology changed June 13, 2022.",
    ),
)
