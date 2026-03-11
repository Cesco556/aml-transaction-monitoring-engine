"""Fuzzy name matching engine with multiple algorithms.

Supports exact, Levenshtein, Jaro-Winkler, and phonetic (Soundex/Metaphone)
matching.  Falls back to basic implementations if third-party libraries
(rapidfuzz, jellyfish) are unavailable.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Optional dependency imports — fall back to basic implementations
# ---------------------------------------------------------------------------

try:
    from rapidfuzz.distance import Levenshtein as _rf_lev
    from rapidfuzz.fuzz import ratio as _rf_ratio  # noqa: F401

    def _levenshtein_distance(a: str, b: str) -> int:
        return _rf_lev.distance(a, b)

    def _jaro_winkler_similarity(a: str, b: str) -> float:
        from rapidfuzz.distance import JaroWinkler

        return JaroWinkler.similarity(a, b)

    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover
    _HAS_RAPIDFUZZ = False

    def _levenshtein_distance(a: str, b: str) -> int:  # type: ignore[misc]
        """Basic Levenshtein via Wagner-Fischer."""
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            curr = [i + 1] + [0] * len(b)
            for j, cb in enumerate(b):
                cost = 0 if ca == cb else 1
                curr[j + 1] = min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost)
            prev = curr
        return prev[-1]

    def _jaro_winkler_similarity(a: str, b: str) -> float:  # type: ignore[misc]
        """Basic Jaro-Winkler implementation."""
        if a == b:
            return 1.0
        len_a, len_b = len(a), len(b)
        if len_a == 0 or len_b == 0:
            return 0.0
        match_dist = max(len_a, len_b) // 2 - 1
        a_matches = [False] * len_a
        b_matches = [False] * len_b
        matches = 0
        transpositions = 0
        for i in range(len_a):
            start = max(0, i - match_dist)
            end = min(i + match_dist + 1, len_b)
            for j in range(start, end):
                if b_matches[j] or a[i] != b[j]:
                    continue
                a_matches[i] = True
                b_matches[j] = True
                matches += 1
                break
        if matches == 0:
            return 0.0
        k = 0
        for i in range(len_a):
            if not a_matches[i]:
                continue
            while not b_matches[k]:
                k += 1
            if a[i] != b[k]:
                transpositions += 1
            k += 1
        jaro = (matches / len_a + matches / len_b + (matches - transpositions / 2) / matches) / 3
        # Winkler boost
        prefix = 0
        for i in range(min(4, len_a, len_b)):
            if a[i] == b[i]:
                prefix += 1
            else:
                break
        return jaro + prefix * 0.1 * (1 - jaro)


try:
    import jellyfish as _jf

    def _soundex(s: str) -> str:
        return _jf.soundex(s) if s else ""

    def _metaphone(s: str) -> str:
        return _jf.metaphone(s) if s else ""

    _HAS_JELLYFISH = True
except ImportError:  # pragma: no cover
    _HAS_JELLYFISH = False

    def _soundex(s: str) -> str:  # type: ignore[misc]
        """Basic Soundex implementation."""
        if not s:
            return ""
        s = s.upper()
        coded = s[0]
        mapping = {
            "B": "1", "F": "1", "P": "1", "V": "1",
            "C": "2", "G": "2", "J": "2", "K": "2", "Q": "2", "S": "2", "X": "2", "Z": "2",
            "D": "3", "T": "3",
            "L": "4",
            "M": "5", "N": "5",
            "R": "6",
        }
        for ch in s[1:]:
            code = mapping.get(ch, "0")
            if code != "0" and code != coded[-1]:
                coded += code
            if len(coded) == 4:
                break
        return (coded + "0000")[:4]

    def _metaphone(s: str) -> str:  # type: ignore[misc]
        """Simplified Metaphone — uses Soundex as fallback."""
        return _soundex(s)


# ---------------------------------------------------------------------------
# Common name variations for pre-processing
# ---------------------------------------------------------------------------

_NAME_ALIASES: dict[str, str] = {
    "mohammed": "muhammad",
    "mohammad": "muhammad",
    "muhammed": "muhammad",
    "mohamad": "muhammad",
    "mohamed": "muhammad",
    "limited": "ltd",
    "corporation": "corp",
    "company": "co",
    "incorporated": "inc",
    "mister": "mr",
    "missus": "mrs",
    "doctor": "dr",
    "junior": "jr",
    "senior": "sr",
    "saint": "st",
    "robert": "robert",
    "william": "william",
    "alexander": "alexander",
    "abdel": "abd",
    "abdul": "abd",
    "bin": "bin",
    "ibn": "bin",
}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_MULTI_SPACE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Normalise a name for comparison: lowercase, strip accents, remove
    punctuation, collapse whitespace, and apply common alias substitutions."""
    if not name:
        return ""
    # Unicode NFKD decomposition → strip combining characters → lowercase
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    # Remove punctuation
    text = _PUNCT_RE.sub(" ", text)
    text = _MULTI_SPACE.sub(" ", text).strip()
    # Apply alias substitutions (word-level)
    words = text.split()
    words = [_NAME_ALIASES.get(w, w) for w in words]
    return " ".join(words)


# ---------------------------------------------------------------------------
# Match result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchResult:
    """Result of a name matching comparison."""

    score: float  # 0.0 – 1.0
    algorithm: str
    query: str
    target: str


# ---------------------------------------------------------------------------
# Individual algorithm functions
# ---------------------------------------------------------------------------


def exact_match(query: str, target: str) -> float:
    """Return 1.0 if normalised strings are identical, else 0.0."""
    return 1.0 if normalize_name(query) == normalize_name(target) else 0.0


def levenshtein_similarity(query: str, target: str) -> float:
    """Normalised Levenshtein similarity (1 - distance/max_len)."""
    a, b = normalize_name(query), normalize_name(target)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    dist = _levenshtein_distance(a, b)
    return 1.0 - dist / max(len(a), len(b))


def jaro_winkler(query: str, target: str) -> float:
    """Jaro-Winkler similarity on normalised names."""
    return _jaro_winkler_similarity(normalize_name(query), normalize_name(target))


def phonetic_match(query: str, target: str) -> float:
    """Phonetic matching using Soundex and Metaphone.

    Compares each word pair; returns average of per-word best matches.
    """
    a_words = normalize_name(query).split()
    b_words = normalize_name(target).split()
    if not a_words or not b_words:
        return 0.0

    total = 0.0
    for aw in a_words:
        best = 0.0
        for bw in b_words:
            sx_match = 1.0 if _soundex(aw) == _soundex(bw) else 0.0
            mp_match = 1.0 if _metaphone(aw) == _metaphone(bw) else 0.0
            best = max(best, sx_match, mp_match)
        total += best
    return total / len(a_words)


# ---------------------------------------------------------------------------
# Algorithm registry
# ---------------------------------------------------------------------------

ALGORITHMS: dict[str, callable] = {
    "exact": exact_match,
    "levenshtein": levenshtein_similarity,
    "jaro_winkler": jaro_winkler,
    "phonetic": phonetic_match,
}

DEFAULT_ALGORITHMS = ["exact", "jaro_winkler", "levenshtein", "phonetic"]
DEFAULT_THRESHOLD = 0.85


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def match_name(
    query: str,
    target: str,
    *,
    algorithms: list[str] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> MatchResult | None:
    """Match *query* against *target* using multiple algorithms.

    Returns the best :class:`MatchResult` whose score ≥ *threshold*, or
    ``None`` if no algorithm exceeds the threshold.
    """
    algos = algorithms or DEFAULT_ALGORITHMS
    best_score = 0.0
    best_algo = ""
    for algo_name in algos:
        fn = ALGORITHMS.get(algo_name)
        if fn is None:
            continue
        score = fn(query, target)
        if score > best_score:
            best_score = score
            best_algo = algo_name
    if best_score < threshold:
        return None
    return MatchResult(
        score=round(best_score, 4),
        algorithm=best_algo,
        query=query,
        target=target,
    )
