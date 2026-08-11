"""
Fuzzy / alias application matching.

Never guess when multiple strong matches exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from tools.applications.discovery import load_registry, normalize_name


@dataclass
class MatchResult:
    status: str  # matched | ambiguous | not_found
    query: str
    matches: list[dict[str, Any]]
    message: str

    @property
    def entry(self) -> dict[str, Any] | None:
        if self.status == "matched" and self.matches:
            return self.matches[0]
        return None


def _score(query: str, entry: dict[str, Any]) -> float:
    q = normalize_name(query)
    candidates = [normalize_name(entry.get("display_name", ""))] + [
        normalize_name(a) for a in entry.get("aliases", [])
    ]

    best = 0.0
    for candidate in candidates:
        if not candidate:
            continue
        if q == candidate:
            return 1.0
        if q in candidate or candidate in q:
            best = max(best, 0.92)
        best = max(best, SequenceMatcher(None, q, candidate).ratio())
    return best


def match_application(
    application_name: str,
    registry: dict[str, dict[str, Any]] | None = None,
    threshold: float = 0.72,
) -> MatchResult:
    query = application_name.strip()
    if not query:
        return MatchResult(
            status="not_found",
            query=query,
            matches=[],
            message="No application name provided.",
        )

    registry = registry if registry is not None else load_registry()
    scored: list[tuple[float, dict[str, Any]]] = []

    for entry in registry.values():
        score = _score(query, entry)
        if score >= threshold:
            scored.append((score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return MatchResult(
            status="not_found",
            query=query,
            matches=[],
            message=f"I could not find an application matching '{query}'.",
        )

    exact = [entry for score, entry in scored if score >= 0.999]
    if len(exact) == 1:
        entry = exact[0]
        return MatchResult(
            status="matched",
            query=query,
            matches=[entry],
            message=f"Matched {entry['display_name']}.",
        )
    if len(exact) > 1:
        names = [e["display_name"] for e in exact[:5]]
        return MatchResult(
            status="ambiguous",
            query=query,
            matches=exact[:5],
            message=(
                f"I found {len(exact)} applications matching '{query}': "
                + ", ".join(names)
                + ". Which one should I open?"
            ),
        )

    top_score = scored[0][0]
    close = [
        entry
        for score, entry in scored
        if score >= max(threshold, top_score - 0.08)
    ]

    if len(close) == 1:
        entry = close[0]
        return MatchResult(
            status="matched",
            query=query,
            matches=[entry],
            message=f"Matched {entry['display_name']}.",
        )

    names = [e["display_name"] for e in close[:5]]
    return MatchResult(
        status="ambiguous",
        query=query,
        matches=close[:5],
        message=(
            f"I found {len(close)} applications matching '{query}': "
            + ", ".join(names)
            + ". Which one should I open?"
        ),
    )
