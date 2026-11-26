"""Enterprise lenses: tech firms, new firms, sole traders (GUS REGON), patents and R&D spending (GUS DBW) and
new industrial buildings (GUNB permit register).

The base lens builder (lenses.py) spreads the values over the map. This module only names the interim tables
and fields and the lens text. Lens notes name the level and a period that stays true after a refresh; the exact
dates are in each source's vintage, shown on the legend's source line.
"""

from __future__ import annotations

from .lenses_more_a import _metric, _spec

GROUPS_C = [{"id": "enterprise", "name": "Enterprise", "icon": "i-manufacturing"}]
REQUIRES_C = ["pl_econ_regon", "pl_econ_innovation", "pl_econ_permits"]

_TECH = _metric(
    "ict_share",
    "Tech and media firms",
    "pct",
    "of registered firms",
    "gmina",
    "pl_econ_regon",
    "Share of all firms and other entities in the REGON register that work in information and communication "
    "(software, IT services, telecoms, media) (GUS).",
    "enterprise",
)
_NEW = _metric(
    "new_entities_per_1000",
    "New firms",
    "float",
    "per 1,000 residents",
    "gmina",
    "pl_econ_regon",
    "Firms and other entities newly entered in the REGON register in the last 12 months, per 1,000 residents (GUS).",
    "enterprise",
)
_SOLE = _metric(
    "sole_traders_per_1000",
    "Sole traders",
    "float",
    "per 1,000 residents",
    "gmina",
    "pl_econ_regon",
    "People who run their own business, per 1,000 residents of all ages (GUS REGON).",
    "enterprise",
)
_PATENTS = _metric(
    "patents_per_100k",
    "Patents",
    "float",
    "per 100,000 residents",
    "powiat",
    "pl_econ_innovation",
    "Patents granted in the two latest published years together, per 100,000 residents, counted where the first "
    "applicant is based (GUS).",
    "enterprise",
)
_RD = _metric(
    "rd_spending_per_resident",
    "R&D spending",
    "pln",
    "z\u0142 per resident",
    "voivodeship",
    "pl_econ_innovation",
    "Spending on research and development by companies, universities, institutes and government, per resident, "
    "in the latest published year (GUS).",
    "enterprise",
)
_INDUSTRY = _metric(
    "new_industrial_decisions",
    "New factories and warehouses",
    "int",
    "permit decisions",
    "gmina",
    "pl_econ_permits",
    "Building permits for new industrial and storage buildings (factories, warehouses, cold stores) issued in the "
    "last 24 months (GUNB register).",
    "enterprise",
)

LENSES_C = [
    _spec("tech_firms", _TECH, "i-information", "\U0001f4bb", "blue", "linear",
          "regon_gmina", "ict_share", "Per gmina, latest month. Firms are counted at their registered address.",
          percent=True),
    _spec("new_firms", _NEW, "d-commercial-hub", "\U0001f331", "teal", "linear",
          "regon_gmina", "new_entities_per_1000", "Per gmina, last 12 months."),
    _spec("sole_traders", _SOLE, "i-professional", "\U0001f4bc", "gold", "linear",
          "regon_gmina", "sole_traders_per_1000",
          "Per gmina, latest month. Counted at the registered address, often the owner's home."),
    _spec("patents", _PATENTS, "y-science", "\U0001f4dc", "violet", "linear",
          "patents_powiat", "patents_per_100k", "Per powiat, two latest years together."),
    _spec("rd_spending", _RD, "d-campus", "\U0001f52c", "mako", "linear",
          "rd_voivodeship", "rd_spending_per_resident", "Per voivodeship, latest year."),
    _spec("new_industry", _INDUSTRY, "d-industrial-zone", "\U0001f3ed", "fire", "linear",
          "industrial_permits_gmina", "new_industrial_decisions",
          "Per gmina, last 24 months. A count of decisions, not of floor area."),
]
LENSES_C[-1][6]["short_name"] = "New industry"  # the dock has little room
