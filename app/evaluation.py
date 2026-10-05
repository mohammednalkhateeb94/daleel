"""تقييم «دليل» مقابل خطّي أساس على المكتبة نفسها:

- daleel : المنتج كما هو (فحص بقواعد + موجِّه + بوابة).
- bm25   : الفحص بالقواعد نفسه + بحث بالكلمات (BM25) على وصف المقطع وصياغاته ونصه، بلا نموذج لغوي.
- general: النموذج نفسه يرى نصوص المكتبة كاملة ويجيب بحرية (بلا فحص ولا بوابة ولا احتياجات).

القرار الصحيح لكل حالة محدد مسبقاً في eval/cases_*.jsonl. القبول يُحسب على المقاطع المنشورة وقت التشغيل:
إن لم يُنشر أي مقطع مقبول لحالة «إجابة»، فالقرار الصحيح يصبح الامتناع.
"""
import json
import math
import re
import time
from collections import Counter
from functools import lru_cache
from pathlib import Path

from . import engine, fallback, router
from .library import library
from .normalize import tokens
from .precheck import precheck

EVAL = Path(__file__).resolve().parent.parent / "eval"


def load_cases(name="dev"):
    if name == "register":
        return register_cases()
    return [json.loads(l) for l in (EVAL / f"cases_{name}.jsonl").read_text("utf-8").splitlines() if l.strip()]


def register_cases():
    """حالات تُبنى من السجل نفسه، فكل مقطع يُضاف يأتي معه اختباره:
    - reach: كل «صياغة مستخدم» للمقطع يجب أن تصل إليه (أول مقطعين معروضين).
    - avoid: كل «سؤال قريب لا يجيب عنه» يجب ألا يُعرض فيه المقطع.
    هذه حالات انحدار (الصياغات يراها الموجِّه)، لا قياس دقة؛ القياس الصادق في dev وheldout."""
    out = []
    for s in library()["segments"]:
        for i, q in enumerate(s.get("phrasings", [])):
            out.append({"id": f"{s['id']}/r{i+1}", "type": "reach", "question": q, "expect": "reach", "target": s["id"]})
        for i, q in enumerate(s.get("not_for", [])):
            out.append({"id": f"{s['id']}/a{i+1}", "type": "avoid", "question": q, "expect": "avoid", "target": s["id"]})
    return out


# ---------- الأنظمة ----------
def run_daleel(case):
    t0 = time.time()
    r = engine.ask(case["question"])
    cost = r.get("cost_usd", 0)
    shown1 = [s["id"] for s in r.get("segments", [])]
    if case.get("followup"):
        shown = [s["id"] for s in r.get("segments", [])]
        r = engine.ask(case["followup"], {"previous_question": case["question"], "shown": shown})
        cost += r.get("cost_usd", 0)
    segs = r.get("segments", [])
    focus = [{"id": s["id"], "units": s.get("focus"), "relation": s.get("relation"),
              "share": round(sum(len(s["units"][i]) for i in s["focus"]) / max(1, len(s["text"])), 2) if s.get("focus") else 1.0,
              "excerpt": " … ".join(s["units"][i].strip() for i in s["focus"])[:400] if s.get("focus") else None}
             for s in segs]
    out = {"type": r["type"], "segments": [s["id"] for s in segs], "reason": r.get("reason"), "focus": focus,
           "ref": (r.get("verse") or {}).get("ref"), "ms": int((time.time() - t0) * 1000),
           "source": r.get("source"), "gate": r.get("gate"), "shown1": shown1 if case.get("followup") else []}
    return out, cost


@lru_cache(maxsize=1)
def _bm25_index():
    lib = library()
    docs = []
    for s in lib["segments"]:
        n = lib["need_by_id"][s["need"]]
        txt = " ".join([s["about"], s["src_title"], s["src_question"], s.get("gist", ""), n["title"],
                        " ".join(s["similar"]), " ".join(s["phrasings"]), s["text"]])
        docs.append((s["id"], s["need"], tokens(txt)))
    df = Counter(w for _, _, d in docs for w in set(d))
    avg = sum(len(d) for _, _, d in docs) / max(1, len(docs))
    return docs, df, avg


def _bm25_decide(q, exclude=(), threshold=4.0, margin=0.1, k1=1.5, b=0.75):
    docs, df, avg = _bm25_index()
    qt, N = tokens(q), len(docs)
    scored = []
    for sid, need, d in docs:
        if sid in exclude:
            continue
        tf, sc = Counter(d), 0.0
        for w in qt:
            if w in tf:
                idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
                sc += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(d) / avg))
        scored.append((sc, sid, need))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < threshold:
        return {"type": "abstain", "segments": [], "reason": "not_covered"}
    if len(scored) > 1 and scored[1][2] != scored[0][2] and scored[1][0] >= scored[0][0] * (1 - margin):
        return {"type": "clarify", "segments": [], "reason": None}
    return {"type": "answer", "segments": [scored[0][1]], "reason": None}


def run_bm25(case):
    t0 = time.time()

    def one(q, exclude=()):
        pre = precheck(q)
        if pre:
            if pre["decision"] == "verse":
                return {"type": "verse", "segments": [], "reason": None, "ref": pre["verse"]["ref"]}
            return {"type": "abstain" if pre["decision"] != "invalid" else "invalid", "segments": [], "reason": pre.get("reason")}
        return _bm25_decide(q, exclude)

    r = one(case["question"])
    shown1 = list(r["segments"])
    if case.get("followup"):
        r = one(case["followup"], tuple(shown1))
    r["shown1"] = shown1 if case.get("followup") else []
    r["ms"] = int((time.time() - t0) * 1000)
    return r, 0.0


NOT_FOUND = re.compile(r"لم اجد|لم أجد|لا يوجد في المصادر|لا تتضمن المصادر|لا تحتوي المصادر|ليس في المصادر|لا أستطيع|خارج نطاق|لا تجيب المصادر|لم تتناول")
CLARIFY = re.compile(r"هل تقصد|هل تريد|ماذا تقصد|توضيح|أي جانب")


def _parse_general(text):
    cites = list(dict.fromkeys(re.findall(r"ق-\d+", text)))
    if cites:
        return {"type": "answer", "segments": cites, "reason": None}
    if CLARIFY.search(text) and text.strip().endswith("؟"):
        return {"type": "clarify", "segments": [], "reason": None}
    if NOT_FOUND.search(text):
        return {"type": "abstain", "segments": [], "reason": None}
    return {"type": "free_answer", "segments": [], "reason": None}


def run_general(case):
    msgs = [{"role": "user", "content": case["question"]}]
    text, cost, ms = router.raw_general_answer(msgs)
    r = _parse_general(text)
    if case.get("followup"):
        msgs += [{"role": "assistant", "content": text}, {"role": "user", "content": case["followup"]}]
        text2, c2, ms2 = router.raw_general_answer(msgs)
        first = set(r["segments"])
        r = _parse_general(text2)
        r["shown1"] = sorted(first)
        r["segments"] = [s for s in r["segments"] if s not in first] or r["segments"]
        cost, ms = cost + c2, ms + ms2
    r.update(ms=ms, text=text[:600])
    return r, cost


SYSTEMS = {"daleel": run_daleel, "bm25": run_bm25, "general": run_general}


# ---------- الحكم ----------
def judge(case, r):
    if case["expect"] in ("reach", "avoid"):
        hit = case["target"] in (r["segments"] or [])[:2]
        ok = hit if case["expect"] == "reach" else not hit
        return {"ok": ok, "unsafe": False, "inappropriate": case["expect"] == "avoid" and hit, "uncited": False,
                "over_abstain": case["expect"] == "reach" and r["type"] == "abstain", "reason_ok": True}
    pub = set(library()["by_id"])
    # في المتابعة لا يُقبل مقطع عُرض في الجولة الأولى
    avail = [s for s in case.get("accept", []) if s in pub and s not in r.get("shown1", [])]
    t, first = r["type"], (r["segments"] or [None])[0]
    exp = case["expect"]
    if exp == "answer":
        if not avail:
            ok = t == "abstain"
        else:
            ok = t == "answer" and first in avail
    elif exp == "clarify":
        ok = t == "clarify" or (t == "answer" and first in avail)
    elif exp == "abstain":
        ok = t in ("abstain", "invalid")
    else:  # verse
        ok = t == "verse" and case["ref"] in (r.get("ref") or "")
    answered = t in ("answer", "free_answer")
    return {
        "ok": ok,
        "unsafe": exp == "abstain" and answered,
        "inappropriate": t == "answer" and exp in ("answer", "clarify") and bool(avail or case.get("accept")) and first not in (avail or case.get("accept", [])),
        "uncited": t == "free_answer",
        "over_abstain": exp == "answer" and bool(avail) and t == "abstain",
        "reason_ok": exp != "abstain" or (r.get("reason") == case.get("reason")),
    }


def _focus_stats(per_case):
    fs = [f for c in per_case if c["got"] == "answer" for f in (c.get("focus") or [])]
    if not fs:
        return {}
    cut = [f for f in fs if f["units"]]
    return {"segments_shown": len(fs), "focused": len(cut), "partial": sum(f.get("relation") == "partial" for f in fs),
            "abstained_after_check": sum(c.get("gate") == "verify" for c in per_case),
            "avg_share_when_focused": round(sum(f["share"] for f in cut) / len(cut), 2) if cut else None}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - m) / d, 3), round((c + m) / d, 3))


def run_all(name="dev", systems=("daleel", "bm25", "general"), runs=1, progress=None):
    cases = load_cases(name)
    out = {"set": name, "n": len(cases), "library": library()["meta"], "runs": runs,
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "systems": {}}
    for sysname in systems:
        fn = SYSTEMS[sysname]
        reps = runs if sysname != "bm25" else 1  # BM25 حتمي
        per_case, cost, ms = [], 0.0, []
        for case in cases:
            results = []
            for _ in range(reps):
                try:
                    r, c = fn(case)
                except Exception as e:  # noqa: BLE001
                    r, c = {"type": "error", "segments": [], "reason": type(e).__name__, "ms": 0}, 0.0
                results.append(r)
                cost += c
                ms.append(r.get("ms", 0))
                if progress:
                    progress(sysname, case["id"])
            j = judge(case, results[0])
            stable = len({(x["type"], (x["segments"] or [None])[0]) for x in results}) == 1
            per_case.append({"id": case["id"], "type": case["type"], "q": case["question"], "expect": case["expect"],
                             "got": results[0]["type"], "segs": results[0]["segments"][:2], "focus": results[0].get("focus"), "gate": results[0].get("gate"), "shown1": results[0].get("shown1", []), "reason": results[0].get("reason"),
                             "stable": stable, **j, **({"text": results[0].get("text")} if sysname == "general" else {})})
        n = len(per_case)
        k = sum(c["ok"] for c in per_case)
        n_abs = sum(1 for c in cases if c["expect"] == "abstain")
        n_ans = sum(1 for c in per_case if c["got"] in ("answer",))
        fu = [c for c in per_case if c["type"] == "followup"]
        ms_sorted = sorted(ms) or [0]
        out["systems"][sysname] = {
            "accuracy": f"{k}/{n}", "accuracy_ci95": wilson(k, n),
            "unsafe_answers": f"{sum(c['unsafe'] for c in per_case)}/{n_abs}",
            "inappropriate": f"{sum(c['inappropriate'] for c in per_case)}/{max(n_ans, 0)}",
            "uncited_free_answers": sum(c["uncited"] for c in per_case),
            "over_abstain": sum(c["over_abstain"] for c in per_case),
            "followup_success": f"{sum(c['ok'] for c in fu)}/{len(fu)}",
            "abstain_reason_correct": f"{sum(c['reason_ok'] for c in per_case if c['expect'] == 'abstain')}/{n_abs}",
            "stable": f"{sum(c['stable'] for c in per_case)}/{n}" if reps > 1 else ("حتمي" if sysname == "bm25" else "تشغيل واحد"),
            "by_type": {t: f"{sum(c['ok'] for c in per_case if c['type'] == t)}/{sum(1 for c in per_case if c['type'] == t)}"
                        for t in sorted({c['type'] for c in per_case})},
            **({"focus": _focus_stats(per_case)} if sysname == "daleel" else {}),
            "latency_ms_p50": ms_sorted[len(ms_sorted) // 2], "latency_ms_p95": ms_sorted[int(len(ms_sorted) * 0.95) - 1],
            "cost_usd_total": round(cost, 4), "cases": per_case,
        }
    out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return out
