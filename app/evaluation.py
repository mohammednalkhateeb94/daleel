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
from pathlib import Path

from . import engine, router
from .library import library

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
           "source": r.get("source"), "gate": r.get("gate"), "shown1": shown1 if case.get("followup") else [],
           "method": r.get("method")}
    return out, cost


def shadow_result(r):
    """النتيجة التي كانت ستظهر لو فُعّلت بوابة G2-المهمة (من سجل الظل)، لتُحكم بالمعيار نفسه."""
    m = r.get("method") or {}
    if r.get("type") != "answer" or "shadow_segments" not in m:
        return r
    if m.get("proposed") == "NOT_COVERED":
        return {**r, "type": "abstain", "segments": [], "reason": "not_covered"}
    return {**r, "segments": m["shadow_segments"]}


def run_bm25(case):
    """خط الأساس = مسار البديل في المنتج نفسه (فحص بالقواعد + BM25 + البوابة)، لا تطبيق منفصل."""
    t0 = time.time()

    def one(q, exclude=()):
        r = engine.ask(q, {"previous_question": case["question"], "shown": list(exclude)} if exclude else None, use_llm=False)
        return {"type": r["type"], "segments": [s["id"] for s in r.get("segments", [])], "reason": r.get("reason"),
                "ref": (r.get("verse") or {}).get("ref")}

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


def run_general_pre(case):
    """خط أساس رابع منصف: النموذج العام نفسه، لكن بعد الفحص بالقواعد الذي يمر به «دليل» والبحث بالكلمات.
    ما يلتقطه الفحص يُعامل كما في المنتج، وما بعده يجيب عنه النموذج بحرية من النصوص."""
    from .precheck import precheck
    pre = precheck(case["question"])
    if pre:
        t0 = time.time()
        r = engine.ask(case["question"], use_llm=False)
        out = {"type": r["type"], "segments": [s["id"] for s in r.get("segments", [])], "reason": r.get("reason"),
               "ref": (r.get("verse") or {}).get("ref"), "shown1": [], "ms": int((time.time() - t0) * 1000)}
        return out, 0.0
    return run_general(case)


SYSTEMS = {"daleel": run_daleel, "bm25": run_bm25, "general": run_general, "general_pre": run_general_pre}


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


def _method_stats(per_case):
    """شروط تفعيل G2 الثلاثة: لا تراجع في الناجح، وإصلاح خطأ واحد على الأقل، وعدم زيادة غير المناسب."""
    ms = [c for c in per_case if c.get("method")]
    regress = [c["id"] for c in per_case if c["ok"] and not c.get("shadow_ok", c["ok"])]
    fixes = [c["id"] for c in per_case if not c["ok"] and c.get("shadow_ok", c["ok"])]
    inap_now = sum(c["inappropriate"] for c in per_case)
    inap_shadow = sum(c.get("shadow_inappropriate", c["inappropriate"]) for c in per_case)
    from collections import Counter
    return {
        "decisions": dict(Counter(c["method"].get("decision") for c in ms)),
        "tasks": dict(Counter(c["method"].get("task") for c in ms if c["method"].get("task"))),
        "sensitivity": dict(Counter(c["method"].get("sensitivity") for c in ms if c["method"].get("sensitivity"))),
        "g2_would_block": sorted({c["id"] for c in ms if False in (c["method"].get("g2") or {}).values()}),
        "proposed_differs": sorted(c["id"] for c in ms if c["method"].get("proposed") != c["method"].get("decision")),
        "g4_blocked_cases": sorted(c["id"] for c in ms if c["method"].get("g4_blocked")),
        "g2_activation": {"accuracy_now": f"{sum(c['ok'] for c in per_case)}/{len(per_case)}",
                          "accuracy_if_enabled": f"{sum(c.get('shadow_ok', c['ok']) for c in per_case)}/{len(per_case)}",
                          "regressions": regress, "fixes": fixes,
                          "inappropriate_now": inap_now, "inappropriate_if_enabled": inap_shadow,
                          "conditions_met": not regress and bool(fixes) and inap_shadow <= inap_now},
    }


def _focus_stats(per_case):
    fs = [f for c in per_case if c["got"] == "answer" for f in (c.get("focus") or [])]
    if not fs:
        return {}
    cut = [f for f in fs if f["units"]]
    return {"segments_shown": len(fs), "focused": len(cut), "partial": sum(f.get("relation") == "partial" for f in fs),
            "abstained_after_check": sum(c.get("gate") == "verify" for c in per_case),
            "avg_share_when_focused": round(sum(f["share"] for f in cut) / len(cut), 2) if cut else None}


def _range(cases, all_results):
    """الدقة في كل تشغيل على حدة (أدنى، أعلى): التذبذب بين التشغيلات يُعلن ولا يُخفى خلف التشغيل الأول."""
    per_run = [sum(judge(c, rs[i])["ok"] for c, rs in zip(cases, all_results)) for i in range(len(all_results[0]))]
    return [min(per_run), max(per_run)]


def mcnemar(b, c):
    """اختبار McNemar الدقيق (ذو طرفين) على الحالات المختلف فيها فقط."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return round(min(1.0, 2 * p), 4)


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - m) / d, 3), round((c + m) / d, 3))


def run_all(name="dev", systems=("daleel", "bm25", "general"), runs=1, progress=None):
    engine.EVAL_CTX.on = True  # سجل التقييم يُوسم فلا يختلط بأسئلة الناس (في خيط التقييم وحده)
    cases = load_cases(name)
    out = {"set": name, "n": len(cases), "library": library()["meta"], "runs": runs,
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "systems": {}}
    for sysname in systems:
        fn = SYSTEMS[sysname]
        reps = runs if sysname != "bm25" else 1  # BM25 حتمي
        per_case, cost, ms, all_results = [], 0.0, [], []
        for case in cases:
            results = []
            all_results.append(results)
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
            if sysname == "daleel":
                js = judge(case, shadow_result(results[0]))
                j["shadow_ok"], j["shadow_inappropriate"] = js["ok"], js["inappropriate"]
            stable = len({(x["type"], (x["segments"] or [None])[0]) for x in results}) == 1
            per_case.append({"id": case["id"], "type": case["type"], "q": case["question"], "expect": case["expect"],
                             "got": results[0]["type"], "segs": results[0]["segments"][:2], "focus": results[0].get("focus"), "gate": results[0].get("gate"), "shown1": results[0].get("shown1", []), "reason": results[0].get("reason"),
                             "stable": stable, "method": results[0].get("method"), **j, **({"text": results[0].get("text")} if sysname == "general" else {})})
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
            "min_max_accuracy_over_runs": _range(cases, all_results) if reps > 1 else None,
            "by_type": {t: f"{sum(c['ok'] for c in per_case if c['type'] == t)}/{sum(1 for c in per_case if c['type'] == t)}"
                        for t in sorted({c['type'] for c in per_case})},
            **({"focus": _focus_stats(per_case), "methodology": _method_stats(per_case)} if sysname == "daleel" else {}),
            "latency_ms_p50": ms_sorted[len(ms_sorted) // 2], "latency_ms_p95": ms_sorted[int(len(ms_sorted) * 0.95) - 1],
            "cost_usd_total": round(cost, 4), "cases": per_case,
        }
    # McNemar الدقيق بين «دليل» وكل نظام على الحالات نفسها: هل الفرق في الدقة دالّ؟
    if "daleel" in out["systems"]:
        base = {c["id"]: c["ok"] for c in out["systems"]["daleel"]["cases"]}
        out["comparisons"] = {}
        for sysname, d in out["systems"].items():
            if sysname == "daleel":
                continue
            other = {c["id"]: c["ok"] for c in d["cases"]}
            b = sum(1 for k in base if base[k] and not other.get(k))
            c_ = sum(1 for k in base if not base[k] and other.get(k))
            out["comparisons"][sysname] = {"daleel_only_right": b, "other_only_right": c_, "mcnemar_p": mcnemar(b, c_)}
    out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return out
