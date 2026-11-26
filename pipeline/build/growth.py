"""Population change for Poland (a helper, not a builder).

growth = population(31 Dec 2025) / population(31 Dec 2015) - 1, a fraction, over growth_years = [2015, 2025].
Both are GUS figures for the same gmina code (pl_stats_population matches codes on their first six TERYT digits).
GUS publishes each year on that year's borders, so a gmina whose borders changed shows that change too: Opole
grew in 2017 by taking land from Dobrzeń Wielki and three other gminas, and in 2025 Szczawa (1207132) was split
from Kamienica and Grabówka (2002162) from Supraśl. Powiat and voivodeship totals are not affected by a change
inside them. A gmina created since 2015 has no 2015 figure and no growth.
"""

from __future__ import annotations

MAX_GROWTH = 2.0  # a sanity cap: suburban gminas grow up to about +100% in ten years; tripling is a code error
BASE_YEAR = 2015


def rate(latest: float | None, earlier: float | None) -> float | None:
    """latest / earlier - 1, 4 decimals; None if either is missing or the change breaks the sanity cap."""
    if latest is None or not earlier:
        return None
    g = latest / earlier - 1
    return round(g, 4) if abs(g) <= MAX_GROWTH else None
