"""Setup A filter: dual institutional resonance."""


def filter_setup_a(candidates: list[dict]) -> list[dict]:
    """Return stocks matching Setup A "dual institutional resonance" criteria.

    Criteria (all must be met):
        1. Liquidity: avg_volume_20d >= 200_000 (>= NT$200M 20-day avg turnover)
        2. Foreign resonance: foreign_5d_net > 0
        3. Trust resonance: trust_5d_net > 0
        4. Price structure: close > ma20
        5. MA direction: ma20_direction == "rising"

    Unselected candidates are omitted from the result.
    """
    selected: list[dict] = []
    for c in candidates:
        if (
            c.get("avg_volume_20d", 0) >= 200_000
            and c.get("foreign_5d_net", 0) > 0
            and c.get("trust_5d_net", 0) > 0
            and c.get("close", 0) > c.get("ma20", float("inf"))
            and c.get("ma20_direction") == "rising"
        ):
            selected.append(
                {
                    **c,
                    "should_include": True,
                    "reason": "雙法人共振，站上20MA且均線向上",
                }
            )
    return selected
