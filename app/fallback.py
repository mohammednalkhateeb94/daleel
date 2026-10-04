"""مطابقة بالكلمات (BM25) على المكتبة نفسها: تعمل بديلاً عند تعطل النموذج، وتُستخدم خطَّ أساس في التقييم."""
import math
from collections import Counter
from functools import lru_cache

from .library import library
from .normalize import tokens


def _doc(s, need):
    parts = [s["about"], s["src_title"], s["src_question"], s.get("gist", ""), need["title"],
             " ".join(s["similar"]), " ".join(s["phrasings"])]
    return tokens(" ".join(parts))


@lru_cache(maxsize=1)
def _index():
    lib = library()
    docs = [(s["id"], s["need"], _doc(s, lib["need_by_id"][s["need"]])) for s in lib["segments"]]
    df = Counter(w for _, _, d in docs for w in set(d))
    avg = sum(len(d) for _, _, d in docs) / max(1, len(docs))
    return docs, df, avg


def bm25(question: str, exclude=(), k1=1.5, b=0.75):
    docs, df, avg = _index()
    q = tokens(question)
    N = len(docs)
    scored = []
    for sid, need, d in docs:
        if sid in exclude:
            continue
        tf = Counter(d)
        sc = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
            sc += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(d) / avg))
        scored.append((sc, sid, need))
    return sorted(scored, reverse=True)


def decide(question: str, exclude=(), threshold=2.5, margin=0.15):
    ranked = bm25(question, exclude)
    if not ranked or ranked[0][0] < threshold:
        return {"decision": "abstain", "reason": "not_covered", "source": "bm25"}
    top = ranked[0]
    if len(ranked) > 1:
        second = ranked[1]
        if second[2] != top[2] and second[0] >= top[0] * (1 - margin):
            return {"decision": "clarify", "options": [top[2], second[2]], "source": "bm25"}
    return {"decision": "answer", "need": top[2], "segments": [top[1]], "fit": "medium", "source": "bm25"}
