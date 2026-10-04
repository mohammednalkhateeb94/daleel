"""نص المصحف: العرض من مصحف مجمع الملك فهد (برواية حفص، عبر quranpedia)، والمطابقة على نص Tanzil المبسّط."""
import json
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from .normalize import norm

DATA = Path(__file__).resolve().parent.parent / "data" / "quran"


@lru_cache(maxsize=1)
def _load():
    hafs = json.loads((DATA / "hafs.json").read_text(encoding="utf-8"))
    simple = json.loads((DATA / "simple-clean.json").read_text(encoding="utf-8"))
    chapters = json.loads((DATA / "chapters.json").read_text(encoding="utf-8"))
    flat = []  # (sura, aya, normalized words)
    index: dict[str, set[int]] = {}
    for s in map(str, range(1, 115)):
        for a, txt in enumerate(simple[s], 1):
            words = norm(txt).split()
            i = len(flat)
            flat.append((int(s), a, words))
            for w in set(words):
                if len(w) >= 3:
                    index.setdefault(w, set()).add(i)
    return hafs, chapters, flat, index


def sura_name(s: int) -> str:
    return _load()[1][str(s)]["name"]


def verse_text(s: int, a: int) -> str:
    return _load()[0][str(s)][a - 1]


def find_verse(text: str, min_ratio: float = 0.72):
    """يبحث عن آية (أو جزء متصل منها) تقارب النص المكتوب. يعيد dict أو None."""
    hafs, chapters, flat, index = _load()
    q = norm(text).split()
    if len(q) < 3:
        return None
    cand: dict[int, int] = {}
    for w in set(q):
        for i in index.get(w, ()):
            cand[i] = cand.get(i, 0) + 1
    if not cand:
        return None
    results = []
    n = len(q)
    for i, _ in sorted(cand.items(), key=lambda kv: -kv[1])[:60]:
        s0, a0, _w = flat[i]
        # آية واحدة أو حتى ثلاث آيات متتالية من السورة نفسها
        words, last = [], i
        for k in range(i, min(i + 3, len(flat))):
            if flat[k][0] != s0:
                break
            words = words + flat[k][2]
            last = k
            spans = [words] if len(words) <= n + 2 else [words[j:j + n] for j in range(0, len(words) - n + 1)]
            for span in spans:
                r = SequenceMatcher(None, q, span).ratio()
                results.append((round(r, 3), s0, a0, flat[k][1], span == q))
            if len(words) >= n:
                break
    if not results:
        return None
    top = max(r[0] for r in results)
    if top < min_ratio:
        return None
    seen, refs = set(), []
    for r, s, a1, a2, exact in sorted(results, key=lambda x: (-x[0], x[3] - x[2])):
        if r < top or (s, a1) in seen:
            continue
        seen.add((s, a1))
        refs.append({"sura": s, "aya": a1, "aya_end": a2, "sura_name": sura_name(s),
                     "text": " ".join(verse_text(s, a) for a in range(a1, a2 + 1)), "exact": exact or r >= 0.999})
    refs = sorted(refs[:3], key=lambda x: (x["sura"], x["aya"]))
    first = refs[0]
    ref = "، ".join(f"{x['sura_name']}: {x['aya']}" + (f"–{x['aya_end']}" if x['aya_end'] != x['aya'] else "") for x in refs[:3])
    return {**first, "ref": ref, "score": top, "all": refs[:3]}
