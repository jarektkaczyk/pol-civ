"""Population change for Poland (a helper, not a builder).

growth = population(31 Dec 2025) / population(31 Dec 2015) - 1, a fraction, over growth_years = [2015, 2025].
Both are GUS figures for the same gmina code (pl_stats_population matches codes on their first six TERYT digits).
GUS publishes each year on that year's borders, so a gmina whose borders changed shows that change too: Opole
grew in 2017 by taking land from Dobrzeń Wielki and three other gminas, and in 2025 Szczawa (1207132) was split
from Kamienica and Grabówka (2002162) from Supraśl. Powiat and voivodeship totals are not affected by a change
inside them. A gmina created since 2015 has no 2015 figure and no growth.
"""

from __future__ import annotations

# Gminas whose borders changed between 31 Dec 2015 and 31 Dec 2025 (GUS territorial changes): Opole took land
# from Dabrowa, Dobrzen Wielki, Komprachcice and Proszkow in 2017; Szczawa was split from Kamienica and Grabowka
# from Suprasl in 2025. Their own 2015-2025 change mixes moved land with real change, so it is null.
EXCHANGES = [
    {"1661011", "1609022", "1609032", "1609042", "1609103"},  # Opole and the four gminas it took land from (2017)
    {"1207052", "1207132"},  # Kamienica and Szczawa, split off in 2025
    {"2002093", "2002162"},  # Suprasl and Grabowka, split off in 2025
]
BORDER_CHANGED = set().union(*EXCHANGES)


def comparable(gminas) -> bool:
    """True when the 2015 and 2025 figures cover the same land: the set holds all or none of each exchange
    group. A single changed gmina, or powiat Opole alone, is not comparable; a voivodeship or Poland is."""
    have = set(gminas)
    return all(not (g & have) or g <= have for g in EXCHANGES)


MAX_GROWTH = 2.0  # a sanity cap: suburban gminas grow up to about +100% in ten years; tripling is a code error
BASE_YEAR = 2015


def rate(latest: float | None, earlier: float | None) -> float | None:
    """latest / earlier - 1, 4 decimals; None if either is missing or the change breaks the sanity cap."""
    if latest is None or not earlier:
        return None
    g = latest / earlier - 1
    return round(g, 4) if abs(g) <= MAX_GROWTH else None
