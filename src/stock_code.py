# -*- coding: utf-8 -*-
"""Shared stock code normalization helpers."""

from __future__ import annotations

from typing import Any, Iterable, List, Tuple


def canonical_stock_code(value: Any) -> str:
    """Normalize ASX alias spellings while preserving other symbols."""
    code = str(value or "").strip().upper()
    if code.endswith(".ASX"):
        return f"{code[:-4]}.AX"
    return code


def canonical_stock_codes(values: Iterable[Any]) -> List[str]:
    """Normalize a sequence of codes and drop duplicates while preserving order."""
    normalized: List[str] = []
    seen: set[str] = set()
    for value in values:
        code = canonical_stock_code(value)
        if not code or code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return normalized


def stock_code_aliases(value: Any) -> Tuple[str, ...]:
    """Return the canonical code plus any supported legacy aliases."""
    code = canonical_stock_code(value)
    if not code:
        return ()
    aliases = [code]
    if code.endswith(".AX"):
        aliases.append(f"{code[:-3]}.ASX")
    return tuple(aliases)
