# apps/data-science/datascience/holidays_calendar.py

"""Population-weighted public holiday shares for the built-in holiday regions.

Each region's share for a day is the fraction of its population on a public
holiday, counting both the actual and the observed day. Runs in the child.
"""

import json
from datetime import date
from pathlib import Path

import holidays

WEIGHTS = json.loads((Path(__file__).resolve().parent / "population_weights.json").read_text())


def daily_shares(region: str, days: set[date]) -> dict[date, tuple[float, str]]:
    """Returns each holiday day's share and the name used by its largest calendar."""
    calendars = WEIGHTS[region]["calendars"]
    total = sum(calendar["population"] for calendar in calendars)
    years = sorted({day.year for day in days})
    shares: dict[date, float] = {}
    names: dict[date, tuple[int, str]] = {}
    for calendar in calendars:
        observed = holidays.country_holidays(
            calendar["country"],
            subdiv=calendar["subdivision"],
            years=years,
            categories=(holidays.PUBLIC,),
            observed=True,
            language="en_US",
        )
        population = calendar["population"]
        for day, name in observed.items():
            if day not in days:
                continue
            shares[day] = shares.get(day, 0.0) + population / total
            if population > names.get(day, (0, ""))[0]:
                names[day] = (population, name)
    # Rounding guards against a share of 1.0000000002 from summed fractions.
    return {day: (min(1.0, round(share, 6)), names[day][1]) for day, share in shares.items()}
