"""Seeded galaxy map for a campaign: background stars and a route of systems.

Pure data, no Textual.  Coordinates are normalised to ``0..1`` with ``x``
growing left to right and ``y`` top to bottom.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from spacefleet.campaign.models import CampaignStatus

SYSTEM_NAMES: tuple[str, ...] = (
    "Port Maw",
    "Kharlos",
    "Lysades",
    "Cyclops Cluster",
    "Orar",
    "Belis Corona",
    "Gethsemane",
    "Brinaga",
    "Rhamah",
    "Fularis",
    "Macharia",
    "Vorik's Reach",
    "Tarantis",
    "Quinrox",
    "Ghoul Stars",
    "Lamentis",
    "Nemesis Tessera",
    "Barbarus",
    "Contqual",
    "Anjelen",
    "Schindlegeist",
    "Dorsis",
    "Ardent's Gate",
    "Sarcelle",
    "Vallis Prime",
    "Morivan",
    "Ostrakon",
    "Helios Drift",
    "Castor's Anvil",
    "Sabran Deep",
    "Ixion",
    "Veyle",
)

SECTOR_NAMES: tuple[str, ...] = (
    "Gothic Sector",
    "Scarus Sector",
    "Calixis Sector",
    "Ultima Segmentum",
    "Obscurus Rift",
    "Koronus Expanse",
    "Helican Subsector",
    "Jericho Reach",
    "Cadian Gate",
    "Periphery Marches",
    "Elysian Drift",
)

MARKERS: dict[str, str] = {
    "cleared": "✓",
    "current": "◉",
    "next": "⚔",
    "unknown": "?",
    "final": "◎",
    "defeated": "✗",
}

# Keep nodes away from the edges so markers and labels fit.
NODE_MARGIN_X = 0.06
NODE_MARGIN_Y = 0.12
MIN_RISE = 0.2


@dataclass(frozen=True)
class GalaxyNode:
    name: str
    x: float
    y: float


@dataclass(frozen=True)
class Galaxy:
    sector_name: str
    stars: tuple[tuple[float, float], ...]
    nodes: tuple[GalaxyNode, ...]


def generate(seed: int, encounters: int = 5) -> Galaxy:
    """Deterministic galaxy for ``seed``: origin plus ``encounters`` systems."""
    rng = random.Random(seed)
    sector = rng.choice(SECTOR_NAMES)
    count = encounters + 1
    names = rng.sample(SYSTEM_NAMES, min(count, len(SYSTEM_NAMES)))
    while len(names) < count:  # more nodes than names: suffix numerals
        names.append(f"{SYSTEM_NAMES[len(names) % len(SYSTEM_NAMES)]} {len(names)}")

    lo_x, hi_x = NODE_MARGIN_X, 1.0 - NODE_MARGIN_X
    lo_y, hi_y = NODE_MARGIN_Y, 1.0 - NODE_MARGIN_Y
    step = (hi_x - lo_x) / max(1, count - 1)
    jitter = step * 0.2
    nodes: list[GalaxyNode] = []
    y = rng.uniform(lo_y, hi_y)
    for i in range(count):
        x = lo_x + i * step
        if 0 < i < count - 1:
            x += rng.uniform(-jitter, jitter)
        if i > 0:
            # Fresh height, clearly off the previous one so legs are not flat.
            prev = y
            while abs((y := rng.uniform(lo_y, hi_y)) - prev) < MIN_RISE:
                pass
        nodes.append(GalaxyNode(names[i], round(x, 4), round(y, 4)))

    stars = tuple(
        (round(rng.random(), 4), round(rng.random(), 4)) for _ in range(rng.randint(40, 80))
    )
    return Galaxy(sector_name=sector, stars=stars, nodes=tuple(nodes))


def node_states(encounter: int, status: CampaignStatus, nodes: int = 6) -> list[str]:
    """State of each route node for the campaign position.

    ``encounter`` is the next battle number (1-based), so the fleet sits at
    node ``encounter - 1`` and fights at node ``encounter``.
    """
    last = nodes - 1
    if status is CampaignStatus.COMPLETED:
        return ["cleared"] * last + ["current"]
    here = max(0, min(encounter - 1, last))
    states: list[str] = []
    for i in range(nodes):
        if i < here:
            states.append("cleared")
        elif i == here:
            states.append("current")
        elif i == here + 1:
            states.append("defeated" if status is CampaignStatus.DEFEATED else "next")
        elif i == last:
            states.append("final")
        else:
            states.append("unknown")
    return states
