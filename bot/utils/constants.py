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

def get_district_from_link(link: str) -> Optional[int]:
    parts = re.split(r"%3A", link, flags=re.IGNORECASE)
    if len(parts) >= 3:
        district_str = parts[2].strip()
        if district_str and district_str[0].isdigit():
            n = int(district_str[0])
            if 0 <= n <= 8:
                return n
    return None