from __future__ import annotations

import re

_SQL_BLOCK = re.compile(r"```sql\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_UNANSWERABLE_PREFIX = re.compile(r"^\s*UNANSWERABLE\s*:\s*", re.IGNORECASE)


def is_unanswerable(text: str) -> tuple[bool, str]:
    """Return (True, reason) if the LLM response signals it cannot answer."""
    m = _UNANSWERABLE_PREFIX.match(text.strip())
    if m:
        reason = text.strip()[m.end() :].strip()
        return True, reason
    return False, ""


def extract_sql(text: str) -> str:
    """Extract SQL from a code-fenced block or from raw text."""
    block = _SQL_BLOCK.search(text)
    if block:
        return block.group(1).strip().rstrip(";")

    # Try to find SELECT / WITH at the start of any line
    select_match = re.search(r"(?:WITH|SELECT)\b.*", text, re.IGNORECASE | re.DOTALL)
    if select_match:
        return select_match.group(0).strip().rstrip(";")

    return text.strip().rstrip(";")
