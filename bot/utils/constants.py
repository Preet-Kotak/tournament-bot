import re
from typing import Optional

DISTRICT_NAMES = {
    0: "Capital Peak",
    1: "Barbarian Camp",
    2: "Wizard Valley",
    3: "Balloon Lagoon",
    4: "Builder's Workshop",
    5: "Dragon Cliffs",
    6: "Golem Quarry",
    7: "Skeleton Park",
    8: "Goblin Mines",
}

# Reverse map: lowercase name → district number, for fast lookups
DISTRICT_NUMBERS: dict[str, int] = {name.lower(): num for num, name in DISTRICT_NAMES.items()}

# ── Qualifier districts ───────────────────────────────────────────────────────
# Fill in the 6 district names used in the qualifier round.
QUALIFIER_DISTRICTS: list[str] = [
    "Capital Peak",
    "Barbarian Camp",
    "Wizard Valley",
    "Balloon Lagoon",
    "Builder's Workshop",
    "Dragon Cliffs",
]


def resolve_district(district: str) -> Optional[int]:
    """Return the district number for a district name string (case-insensitive), or None."""
    return DISTRICT_NUMBERS.get(district.lower())


def get_district_from_link(link: str) -> Optional[int]:
    parts = re.split(r"%3A", link, flags=re.IGNORECASE)
    if len(parts) >= 3:
        district_str = parts[2].strip()
        if district_str and district_str[0].isdigit():
            n = int(district_str[0])
            if 0 <= n <= 8:
                return n
    return None