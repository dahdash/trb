"""Farsi text normalization shared by indexing and querying."""
import re

_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "آ": "ا", "ؤ": "و",
    "‌": " ", "‏": "", "‎": "", "ـ": "",
    **{chr(0x06F0 + i): str(i) for i in range(10)},  # Persian digits
    **{chr(0x0660 + i): str(i) for i in range(10)},  # Arabic digits
})
_DIACRITICS = re.compile(r"[ً-ٰٟ]")
_PUNCT = re.compile(r"[^\w\s]+")


def norm(s: str) -> str:
    s = _DIACRITICS.sub("", s.translate(_MAP)).lower()
    return " ".join(_PUNCT.sub(" ", s).split())


def fts_query(q: str) -> str | None:
    """User text → FTS5 MATCH expression: every token must match, last one as a prefix."""
    toks = [t for t in norm(q).split() if t]
    if not toks:
        return None
    parts = [f'"{t}"' for t in toks[:-1]] + [f'"{toks[-1]}"*']
    return " ".join(parts)


def fa(n) -> str:
    """Number → Persian digits with a Persian thousands separator."""
    return "" if n is None else f"{n:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))
