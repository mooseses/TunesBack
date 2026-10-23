"""Listening Age, based on the "reminiscence bump" theory.

Find the 5-year span of release years you played most (your "formative era")
and work out how old you would be if you were 18 in the middle of it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

WINDOW_SIZE = 5
FORMATIVE_AGE = 18


@dataclass(frozen=True, slots=True)
class ListeningAge:
    age: int
    era_start: int
    era_end: int
    reference_year: int

    @property
    def era_center(self) -> int:
        return self.era_start + WINDOW_SIZE // 2

    @property
    def era_label(self) -> str:
        """e.g. "Mid 00s" for an era centred on 2005."""
        year = self.era_center
        within = year % 10
        prefix = "Early" if within < 4 else ("Mid" if within < 7 else "Late")
        return f"{prefix} {str(year // 10 * 10)[-2:]}s"


def calculate_listening_age(plays_per_year: Mapping[int, int], reference_year: int) -> ListeningAge | None:
    """`plays_per_year` maps release year to plays. Returns None without usable data."""
    valid = {y: c for y, c in plays_per_year.items() if 1900 < y <= reference_year + 1 and c > 0}
    if not valid:
        return None

    best_start, best_sum = min(valid), -1
    for start in range(min(valid), max(valid) + 1):
        total = sum(valid.get(start + i, 0) for i in range(WINDOW_SIZE))
        if total > best_sum:
            best_start, best_sum = start, total

    center = best_start + WINDOW_SIZE // 2
    age = reference_year - (center - FORMATIVE_AGE)
    return ListeningAge(age=age, era_start=best_start, era_end=best_start + WINDOW_SIZE - 1, reference_year=reference_year)
