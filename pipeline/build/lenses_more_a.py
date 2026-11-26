"""Additional statistical lenses for the W11 data-a sources.

The base lens builder owns map spreading and display defaults. This module only
describes interim table lookups and the lens text. Values remain null when a
publisher omits a unit.
"""

from __future__ import annotations

from .plstats import num, optional


def _metric(key, label, fmt, unit, level, source, description, group, higher_is="neutral"):
    return {
        "key": key,
        "label": label,
        "format": fmt,
        "unit": unit,
        "level": level,
        "source": source,
        "higher_is": higher_is,
        "description": description,
        "group": group,
    }


def _data(metric, table, field, *, percent=False, compare=None, result_scale=1):
    return {
        "metric": metric,
        "table": table,
        "field": field,
        "percent": percent,
        "compare": compare,
        "result_scale": result_scale,
    }


def _spec(
    lens_id, metric, icon, emoji, ramp, scale, table, field, note, *, percent=False, compare=None, domain=None,
    result_scale=1,
):
    extra = {
        "_data": _data(metric, table, field, percent=percent, compare=compare, result_scale=result_scale),
        "note": note,
    }
    if domain is not None:
        extra["domain"] = domain
    return (
        lens_id,
        metric["key"],
        icon,
        emoji,
        ramp,
        scale,
        extra,
    )


_PRICE_MEDIAN = _metric(
    "dwelling_price_median",
    "Median dwelling price",
    "pln",
    "z\u0142 per m\u00b2",
    "powiat",
    "pl_stats_prosperity",
    "Median transaction price per square metre of dwellings sold (GUS).",
    "prosperity",
)
_HIGHER_ED = _metric(
    "higher_ed",
    "Higher education",
    "pct",
    "of residents 13+",
    "gmina",
    "pl_census_2021",
    "Residents aged 13 or more with a higher-education diploma (NSP 2021 census, 31 March 2021).",
    "knowledge",
    "good",
)
_DWELLINGS = _metric(
    "dwellings",
    "New dwellings",
    "float",
    "per 1,000 residents",
    "gmina",
    "pl_stats_prosperity",
    "Dwellings completed per 1,000 residents (GUS).",
    "prosperity",
)
_TOURISM = _metric(
    "tourism",
    "Tourist nights",
    "float",
    "nights per resident",
    "powiat",
    "pl_stats_prosperity",
    "Nights spent in tourist accommodation with 10 or more beds per resident (GUS).",
    "life",
)
_TOURISM_CITY = _metric(
    "tourism_city",
    "Tourist nights in selected cities",
    "float",
    "nights per resident",
    "gmina",
    "pl_stats_prosperity",
    "Nights spent in tourist accommodation with 10 or more beds per resident in published cities (GUS).",
    "life",
)
_PRICE_AVERAGE = _metric(
    "dwelling_price_average",
    "Average dwelling price",
    "pln",
    "z\u0142 per m\u00b2",
    "powiat",
    "pl_stats_prosperity",
    "Average transaction price per square metre of dwellings sold (GUS).",
    "prosperity",
)
_BROADBAND = _metric(
    "broadband_100",
    "Fixed broadband 100 Mb/s+",
    "pct",
    "share of addresses",
    "gmina",
    "pl_more_broadband",
    "Addresses with access to fixed broadband of at least 100 Mb/s (UKE).",
    "prosperity",
)
_EXAM_MATHS = _metric(
    "exam_8_maths",
    "Maths exam result",
    "pct",
    "mean score",
    "gmina",
    "pl_more_exams",
    "Mean mathematics result in the grade 8 examination (CKE).",
    "knowledge",
    "good",
)
_MATURA = _metric(
    "matura_pass",
    "Matura pass rate",
    "pct",
    "pass rate",
    "powiat",
    "pl_more_exams",
    "Share of candidates who passed the matura examination (CKE).",
    "knowledge",
    "good",
)
_OWN_INCOME = _metric(
    "own_income",
    "Own income",
    "pln",
    "z\u0142 per resident",
    "gmina",
    "pl_more_finance",
    "Local government's own income per resident (Ministry of Finance).",
    "prosperity",
    "good",
)
_INVESTMENT = _metric(
    "investment_spending",
    "Investment spending",
    "pln",
    "z\u0142 per resident",
    "gmina",
    "pl_more_finance",
    "Local government's investment spending per resident (Ministry of Finance).",
    "prosperity",
)
_DEBT = _metric(
    "debt",
    "Local government debt",
    "pln",
    "z\u0142 per resident",
    "gmina",
    "pl_more_finance",
    "Local government debt per resident (Ministry of Finance).",
    "prosperity",
)
_CARS = _metric(
    "passenger_cars",
    "Passenger cars",
    "float",
    "per 1,000 residents",
    "powiat",
    "pl_more_gus",
    "Registered passenger cars per 1,000 residents (GUS).",
    "life",
)
_ELECTRIC_CARS = _metric(
    "electric_cars",
    "Electric passenger cars",
    "float",
    "per 1,000 residents",
    "powiat",
    "pl_more_gus",
    "Registered battery-electric passenger cars per 1,000 residents (CEPiK).",
    "life",
)
_FARM_AREA = _metric(
    "farm_area",
    "Average farm area",
    "float",
    "ha",
    "gmina",
    "pl_more_gus",
    "Average agricultural holding area in the 2020 Agricultural Census (GUS).",
    "land",
)
_FARM_LAND = _metric(
    "farm_land_share",
    "Land in farms",
    "pct",
    "share of land",
    "gmina",
    "pl_more_gus",
    "Land in agricultural holdings as a share of the gmina's area in the 2020 Agricultural Census (GUS).",
    "land",
)
_VOTE_2015 = _metric(
    "president_2015",
    "President 2015",
    "pct",
    "Andrzej Duda share of valid votes",
    "gmina",
    "pl_soc_elections",
    "Second round: Andrzej Duda's share of valid votes. The rest went to Bronis\u0142aw Komorowski (PKW).",
    "vote",
)
_VOTE_2020 = _metric(
    "president_2020",
    "President 2020",
    "pct",
    "Andrzej Duda share of valid votes",
    "gmina",
    "pl_soc_elections",
    "Second round: Andrzej Duda's share of valid votes. The rest went to Rafa\u0142 Trzaskowski (PKW).",
    "vote",
)
_VOTE_SHIFT = _metric(
    "president_shift_2020_2025",
    "Presidential vote shift, 2020-2025",
    "float",
    "percentage points",
    "gmina",
    "pl_soc_elections",
    "Karol Nawrocki's 2025 second-round share minus Andrzej Duda's 2020 second-round share (PKW).",
    "vote",
)


LENSES_A = [
    _spec("higher_ed", _HIGHER_ED, "l-bachelors", "\U0001f393", "violet", "linear",
          "education_gmina", "higher_share", "Per gmina, 2021.", percent=True),
    _spec("dwellings", _DWELLINGS, "l-home", "\U0001f3d7\ufe0f", "cividis", "linear",
          "housing_gmina", "dwellings_completed_per_1000", "Per gmina, 2025."),
    _spec("tourism", _TOURISM, "l-tourism", "\U0001f9f3", "olive", "linear",
          "tourism_powiat", "overnight_stays_per_person", "Per powiat, 2025; 368 published values."),
    _spec("tourism_city", _TOURISM_CITY, "l-tourism", "\U0001f9f3", "olive", "linear",
          "tourism_gmina", "overnight_stays_per_person", "Per gmina, 2025; 74 published city values."),
    _spec("dwelling_price_median", _PRICE_MEDIAN, "l-home", "\U0001f3e0", "gold", "linear",
          "housing_prices_powiat", "median_dwelling_price_m2", "Per powiat, 2025."),
    _spec("dwelling_price_average", _PRICE_AVERAGE, "l-home", "\U0001f3e0", "gold", "linear",
          "housing_prices_powiat", "average_dwelling_price_m2", "Per powiat, 2025."),
    _spec("broadband_100", _BROADBAND, "l-income", "\U0001f4e1", "blue", "linear",
          "broadband_gmina", "addresses_100mbps_share", "Per gmina, 2025.", percent=True),
    _spec("exam_8_maths", _EXAM_MATHS, "l-bachelors", "\u2797", "violet", "linear",
          "exam_e8", "e8_math_mean_pct", "Per gmina, 2026.", percent=True),
    _spec("matura_pass", _MATURA, "l-bachelors", "\U0001f393", "violet", "linear",
          "exam_matura", "matura_pass_pct", "Per powiat, 2026; Formula 2023.", percent=True),
    _spec("own_income", _OWN_INCOME, "l-income", "\U0001f4b0", "gold", "linear",
          "local_finance", "own_income_per_resident", "Per gmina, 2025."),
    _spec("investment_spending", _INVESTMENT, "l-home", "\U0001f3d7\ufe0f", "cividis", "linear",
          "local_finance", "investment_spending_per_resident", "Per gmina, 2025."),
    _spec("debt", _DEBT, "l-income", "\U0001f4d2", "rust", "linear",
          "local_finance", "debt_per_resident", "Per gmina, 2025."),
    _spec("passenger_cars", _CARS, "l-tourism", "\U0001f697", "cividis", "linear",
          "vehicles_powiat", "passenger_cars_per_1000", "Per powiat, 2025."),
    _spec("electric_cars", _ELECTRIC_CARS, "l-tourism", "\U0001f50b", "teal", "linear",
          "vehicles_powiat", "electric_cars_per_1000", "Per powiat, 2026-10."),
    _spec("farm_area", _FARM_AREA, "l-farmland", "\U0001f69c", "farm", "linear",
          "farms_gmina", "average_farm_area_ha", "Per gmina, 2020."),
    _spec("farm_land_share", _FARM_LAND, "l-farmland", "\U0001f33e", "farm", "linear",
          "farms_gmina", "farm_land_share", "Per gmina, 2020. Land is assigned to the holding's seat.",
          percent=True),
    _spec("vote_2015", _VOTE_2015, "l-vote", "\U0001f5f3\ufe0f", "vote", "linear",
          "president_2015_r2", "duda_share", "Per gmina, 2015.", percent=True, domain=[0.2, 0.8]),
    _spec("vote_2020", _VOTE_2020, "l-vote", "\U0001f5f3\ufe0f", "vote", "linear",
          "president_2020_r2", "duda_share", "Per gmina, 2020.", percent=True, domain=[0.2, 0.8]),
    _spec("vote_shift_2020_2025", _VOTE_SHIFT, "l-vote", "\U0001f5f3\ufe0f", "vote", "linear",
          "president_2025_r2", "nawrocki_share", "Per gmina; change from 2020 to 2025.", percent=True,
          compare=("president_2020_r2", "duda_share", True), domain=[-15, 15], result_scale=100),
]


def lens_values(data: dict, stats, gminas: list[str]) -> tuple[dict, list]:
    """Return the metric and values aligned to current TERYT7 gminas."""
    metric = data["metric"]
    if metric["source"] not in stats.payload:
        stats.payload[metric["source"]] = optional(metric["source"])
    rows = stats.rows(metric["source"], data["table"])
    compare = data.get("compare")
    other = stats.rows(metric["source"], compare[0]) if compare else {}
    level = metric["level"]

    def code(gmina):
        return gmina if level == "gmina" else gmina[:4] if level == "powiat" else gmina[:2]

    def value(row, field, percent):
        v = num((row or {}).get(field))
        return None if v is None else v / 100 if percent else v

    values = []
    for gmina in gminas:
        key = code(gmina)
        current = value(rows.get(key), data["field"], data.get("percent", False))
        if compare:
            previous = value(other.get(key), compare[1], compare[2])
            current = None if current is None or previous is None else current - previous
        if current is not None:
            current *= data.get("result_scale", 1)
        values.append(current)
    return metric, values
