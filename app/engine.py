"""منطق «دليل»: فحص مسبق ← موجِّه (أو بديل BM25) ← بوابة قواعد ← استجابة مبنية من السجل والقوالب فقط."""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import fallback, focus, router
from .library import T, library, need_segments
from .precheck import precheck
from .quran import find_ref, tafsir_link

LOG = Path(os.getenv("DALEEL_LOG", Path(__file__).resolve().parent.parent / "logs" / "decisions.jsonl"))

REASON_TEMPLATE = {
    "fatwa": "ام-02", "qiraat": "ام-03", "scientific": "ام-04", "hadith_request": "ام-05",
    "verse_not_found": "ام-06", "verse_check": "ام-06", "not_covered": "ام-07", "non_arabic": "ام-08",
    "tafsir": "ام-09", "off_topic": "ام-01", "level_c": "ام-07", "outage": "ام-10",
}
CLARIFY_PAIRS = {frozenset({"ح1", "ح7"}): "ست-01", frozenset({"ح2", "ح7"}): "ست-02", frozenset({"ح3", "ح7"}): "ست-03"}


def _log(rec: dict):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def needs_menu():
    lib = library()
    out = []
    for n in lib["needs"]:
        out.append({"id": n["id"], "section": n["section"], "title": n["title"],
                    "available": bool(need_segments(n["id"]))})
    return out


def render_segment(s: dict, focus_idx=None) -> dict:
    lib = library()
    return {
        "units": s["units"], "focus": focus_idx,
        "id": s["id"], "need": s["need"], "need_title": lib["need_by_id"][s["need"]]["title"],
        "about": T("و-04", يجيب_عن=s["about"]) or s["about"],
        "about_note": T("و-05"),
        "src_line": T("و-06", المصدر=s["source"]["title"], عنوان_المسألة=s["src_title"]) if s["src_title"] else "",
        "src_question": s["src_question"], "text": s["text"],
        "source": s["source"], "location": s["location"], "link": s.get("link") or s["source"]["url"], "reviewer": s["reviewer"],
        "footer": T("و-15"),
    }


def _tafsir(s: int, a):
    link = tafsir_link(s, a)
    link["label"] = T("ام-11", الموضع=link["ref"]) or f"اقرأ معنى {link['ref']} في «التفسير الميسر»"
    return link


def _abstain(reason: str, extra: dict | None = None):
    code = REASON_TEMPLATE.get(reason, "ام-07")
    r = {"type": "abstain", "reason": reason, "message": T(code), "template": code}
    if extra:
        r.update(extra)
    return r


def _gate(dec: dict, exclude=()):
    """بوابة القواعد: لا يمر إلا مقطع معتمد في المكتبة، مستواه أ أو ب، وملاءمته كافية."""
    by_id = library()["by_id"]
    if dec.get("decision") == "answer":
        ids = [i for i in dec.get("segments", []) if i in by_id and i not in exclude and by_id[i]["level"] in ("أ", "ب")]
        if not ids or dec.get("fit") == "low":
            return {"decision": "abstain", "reason": "not_covered", "gate": "blocked"}
        dec["segments"] = ids[:2]
    if dec.get("decision") == "clarify":
        opts = [o for o in dec.get("options", []) if o in library()["need_by_id"]]
        if len(opts) < 2:
            return {"decision": "abstain", "reason": "not_covered", "gate": "blocked"}
        dec["options"] = opts[:3]
    return dec


def ask(question: str, ctx: dict | None = None, use_llm: bool = True) -> dict:
    """ctx: {previous_question, shown: [ids]} في حالة «ما الذي بقي؟». النص لا يُحفظ في السجل."""
    ctx = ctx or {}
    exclude = tuple(ctx.get("shown", []))
    did = uuid.uuid4().hex[:12]
    t0 = time.time()
    meta = {}
    pre = precheck(question)
    if pre:
        dec, source = pre, "precheck"
    else:
        dec, source = None, "llm"
        if use_llm:
            for _ in range(2):
                try:
                    out = router.decide(question, ctx)
                    meta = out.pop("_meta", {})
                    dec = {"decision": out["decision"], "need": out.get("need_id"),
                           "segments": out.get("segment_ids", []), "options": out.get("clarify_needs", []),
                           "reason": out.get("abstain_reason"), "fit": out.get("fit")}
                    if dec["decision"] == "answer" and not all(i in library()["by_id"] for i in dec["segments"]):
                        dec = None  # رقم مقطع غير موجود: أعد المحاولة مرة
                        continue
                    break
                except Exception as e:  # noqa: BLE001
                    meta = {"error": type(e).__name__}
                    dec = None
                    break
        if dec is None:
            source = "bm25"
            dec = fallback.decide(question, exclude)
            if use_llm and meta.get("error"):
                dec["outage"] = True
        dec = _gate(dec, exclude)

    d = dec["decision"]
    if d == "invalid":
        resp = {"type": "invalid", "message": T("و-11")}
    elif d == "verse":
        v = dec["verse"]
        resp = {"type": "verse", "message": T("و-13" if v["exact"] else "و-14"),
                "verse": {"text": v["text"], "ref": v["ref"], "sura": v["sura"], "aya": v["aya"]},
                "source_note": "نص المصحف: مصحف مجمع الملك فهد برواية حفص (عبر quranpedia.net).",
                "tafsir": _tafsir(v["sura"], v["aya"])}
    elif d == "abstain":
        reason = dec.get("reason") or "not_covered"
        if exclude and reason == "not_covered":
            resp = {"type": "abstain", "reason": reason, "message": T("و-12"), "template": "و-12"}
        else:
            resp = _abstain(reason)
        if reason == "tafsir":
            if dec.get("verse"):
                v = dec["verse"]
                resp["verse"] = {"text": v["text"], "ref": v["ref"]}
                resp["tafsir"] = _tafsir(v["sura"], v["aya"])
            elif (ref := find_ref(question)):
                resp["tafsir"] = _tafsir(*ref)
    elif d == "clarify":
        code = CLARIFY_PAIRS.get(frozenset(dec["options"][:2]), "ست-04") if len(dec["options"]) == 2 else "ست-04"
        nb = library()["need_by_id"]
        resp = {"type": "clarify", "message": T(code), "template": code,
                "options": [{"id": o, "title": nb[o]["title"]} for o in dec["options"]]}
    else:
        segs = [library()["by_id"][i] for i in dec["segments"]]
        picks = {}
        if source == "llm" and use_llm:
            picks, fmeta = focus.select(question, segs)
            meta.update(fmeta)
            meta["cost_usd"] = round(meta.get("cost_usd", 0) + fmeta.get("focus_cost_usd", 0), 6)
        resp = {"type": "answer", "need": segs[0]["need"], "segments": [render_segment(s, picks.get(s["id"])) for s in segs],
                "ask_feedback": T("و-02"), "fit": dec.get("fit")}
    if dec.get("outage"):
        resp["notice"] = T("ام-10")
    resp["decision_id"] = did
    resp["cost_usd"] = meta.get("cost_usd", 0)
    resp["source"] = source
    resp["needs"] = needs_menu()
    resp["disclosure"] = T("و-01")
    _log({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "id": did, "source": source,
          "type": resp["type"], "reason": resp.get("reason"), "need": resp.get("need"),
          "segments": [s["id"] for s in resp.get("segments", [])], "followup": bool(exclude),
          "focused": [s["id"] for s in resp.get("segments", []) if s.get("focus")],
          "q_chars": len(question or ""), "ms": int((time.time() - t0) * 1000), **meta,
          "library": library()["meta"]["library_version"]})
    return resp


def by_need(need_id: str, exclude=()) -> dict:
    """اختيار من القائمة أو من أزرار الاستيضاح: أول مقطع معتمد للحاجة لم يُعرض بعد."""
    did = uuid.uuid4().hex[:12]
    segs = need_segments(need_id, exclude)
    if not segs:
        resp = {"type": "abstain", "reason": "not_covered", "message": T("و-12" if exclude else "ام-07")}
    else:
        resp = {"type": "answer", "need": need_id, "segments": [render_segment(segs[0])], "ask_feedback": T("و-02")}
    resp.update(decision_id=did, needs=needs_menu(), disclosure=T("و-01"))
    _log({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "id": did, "source": "menu",
          "type": resp["type"], "need": need_id, "segments": [s["id"] for s in resp.get("segments", [])],
          "followup": bool(exclude), "library": library()["meta"]["library_version"]})
    return resp


def feedback(decision_id: str, value: str, need: str | None = None) -> dict:
    _log({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "id": decision_id, "feedback": value})
    if value == "yes":
        nxt = library()["need_by_id"].get(need or "", {}).get("next", [])
        nb = library()["need_by_id"]
        return {"message": T("و-10"), "next": [{"id": n, "title": nb[n]["title"]} for n in nxt if n in nb and need_segments(n)]}
    if value == "partial":
        return {"message": T("و-03")}
    return {"message": T("و-09")}


def start() -> dict:
    return {"disclosure": T("و-01"), "intro": T("و-07"), "privacy": T("و-08"), "needs": needs_menu(),
            "library": library()["meta"]}
