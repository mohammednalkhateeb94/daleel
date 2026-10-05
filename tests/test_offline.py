"""اختبارات لا تحتاج مفتاح النموذج: الفحص المسبق، والآيات، والبوابة، والمكتبة.

    python tests/test_offline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import engine  # noqa: E402
from app.library import library  # noqa: E402

CASES = [
    ("هل يجوز لمس المصحف بدون وضوء؟", "abstain", "fatwa"),
    ("اعطني حديث عن فضل القرآن", "abstain", "hadith_request"),
    ("What is the Quran?", "abstain", "non_arabic"),
    ("ما هي القراءات العشر؟", "abstain", "qiraat"),
    ("الإعجاز العلمي في القرآن", "abstain", "scientific"),
    ("كيف أصلي؟", "abstain", "off_topic"),
    ("ما تفسير قوله تعالى ﴿إنه لقول رسول كريم﴾", "abstain", "tafsir"),
    ("قال تعالى «إنا نحن نزلنا الذكر وإنا له لحافظين»", "verse", None),
    ("؟؟", "invalid", None),
]


def main():
    fails = 0
    for q, t, reason in CASES:
        r = engine.ask(q, use_llm=False)
        ok = r["type"] == t and (reason is None or r.get("reason") == reason)
        fails += not ok
        print("✓" if ok else "✗", q, "→", r["type"], r.get("reason") or "")
    v = engine.ask("قال الله «إنا نحن نزلنا الذكر وإنا له لحافظين»", use_llm=False)
    assert v["verse"]["ref"] == "الحجر: 9" and "لَحَٰفِظُونَ" in v["verse"]["text"], v["verse"]
    # البوابة: مقطع غير موجود أو ملاءمة منخفضة → امتناع
    assert engine._gate({"decision": "answer", "segments": ["ق-999"], "fit": "high"})["decision"] == "abstain"
    assert engine._gate({"decision": "answer", "segments": ["ق-23"], "fit": "low"})["decision"] == "abstain"
    # المتابعة لا تكرر مقطعاً معروضاً
    r = engine.by_need("ح7", exclude=("ق-23", "ق-24", "ق-25", "ق-26", "ق-27"))
    assert r["type"] == "abstain", r
    # كل مقطع في المكتبة مستواه أ أو ب وله مصدر ورابط
    for s in library()["segments"]:
        assert s["level"] in ("أ", "ب") and s["source"]["url"].startswith("http"), s["id"]
        assert "﴿" not in s["text"] or "ۡ" in s["text"] or "ٱ" in s["text"], f"آية بغير رسم المصحف في {s['id']}"
    # التركيز: الوحدات تعيد النص المعتمد حرفياً، ولا يُختار إلا من النص
    from app import focus
    from app.quran import find_ref
    from app.units import split_units
    for s in library()["segments"]:
        assert "".join(s["units"]) == s["text"], s["id"]
    assert split_units("قال: ﴿إِنَّا نَحْنُ. نَزَّلْنَا﴾ وهذا نص طويل بما يكفي ليكون جملة كاملة. وهذه جملة ثانية طويلة بما يكفي أيضاً للاختبار.")[0].count("﴿") == 1
    sel, _, _ = focus.select("سؤال", [library()["by_id"]["ق-11"]])  # بلا مفتاح: يعرض كاملاً
    assert sel == {"ق-11": None}
    # رابط التفسير عند الامتناع
    assert find_ref("ما تفسير آية الكرسي؟") == (2, 255) and find_ref("ما معنى الآية 5 من سورة الفاتحة") == (1, 5)
    t = engine.ask("فسر لي سورة الفاتحة", use_llm=False)
    assert t["reason"] == "tafsir" and "quran.com/ar/1:1/tafsirs" in t["tafsir"]["url"], t
    # أزرار الحاجات: لا يجيب الزر إلا بمقطع أساسي أو محدد له، والحاجة بلا مقطع أساسي لا تظهر متاحة
    from app.library import menu_segments
    for n in engine.needs_menu():
        r = engine.by_need(n["id"])
        if n["available"]:
            sid = r["segments"][0]["id"]
            seg = library()["by_id"][sid]
            assert seg["priority"] == "أساسي" or sid in library()["need_by_id"][n["id"]].get("entry", []), (n["id"], sid)
        else:
            assert r["type"] == "abstain", (n["id"], r)
    assert not any(s["priority"] != "أساسي" for n in library()["needs"] for s in menu_segments(n["id"]) if not n.get("entry"))
    # بوابة الحاجة: مقطع من حاجة أخرى بملاءمة غير عالية → امتناع
    assert engine._gate({"decision": "answer", "need": "ح1", "segments": ["ق-23"], "fit": "medium"})["decision"] == "abstain"
    assert engine._gate({"decision": "answer", "need": "ح7", "segments": ["ق-23"], "fit": "medium"})["decision"] == "answer"
    # الاستيضاح لا يعرض حاجة بلا مقطع
    g = engine._gate({"decision": "clarify", "options": ["ح1", "ح3", "ح7"]})
    assert all(menu_segments(o) for o in g.get("options", [])), g
    g = engine._gate({"decision": "clarify", "options": ["ح1", "ح2", "ح5"]})  # سؤال واسع وخياراته غير مغطّاة: تُعرض المغطّاة
    assert g["decision"] == "clarify" and len(g["options"]) >= 2 and all(menu_segments(o) for o in g["options"]), g
    g = engine._gate({"decision": "clarify", "options": ["ح2", "ح3"]})  # الحاجتان مغطّاتان: يبقى الاستيضاح
    assert g["decision"] == "clarify" and g["options"] == ["ح2", "ح3"], g
    # الفحص بعد الاختيار: «لا يجيب» يُسقط المقطع، و«جزئياً» يُعرض بعنوان «متعلق»
    from app import router
    orig_d, orig_s = router.decide, focus.select
    try:
        router.decide = lambda q, ctx=None: {"decision": "answer", "need_id": "ح3", "segment_ids": ["ق-11", "ق-12"], "fit": "high", "_meta": {}}
        focus.select = lambda q, segs: ({}, {"ق-11": "none", "ق-12": "none"}, {})
        r = engine.ask("سؤال تجريبي عن الجمع")
        assert r["type"] == "abstain" and r.get("gate") == "verify", r
        focus.select = lambda q, segs: ({}, {"ق-11": "partial", "ق-12": "answers"}, {})
        r = engine.ask("سؤال تجريبي عن الجمع")
        assert [x["id"] for x in r["segments"]] == ["ق-12", "ق-11"] and r["segments"][1]["relation"] == "partial", r
        focus.select = lambda q, segs: ({}, {}, {"focus_error": "Timeout"})  # تعطل الفحص: يبقى اختيار الموجِّه
        assert engine.ask("سؤال تجريبي عن الجمع")["type"] == "answer"
    finally:
        router.decide, focus.select = orig_d, orig_s
    # ثغرة «جزئي»: مقطع من حاجة أخرى بحكم «جزئي» لا يُعرض، ومن الحاجة نفسها يُعرض
    try:
        router.decide = lambda q, ctx=None: {"decision": "answer", "need_id": "ح2", "segment_ids": ["ق-11"], "fit": "high", "_meta": {}}
        focus.select = lambda q, segs: ({}, {"ق-11": "partial"}, {})
        r = engine.ask("متى نزل القرآن؟")
        assert r["type"] == "abstain" and r.get("gate") == "verify", r
        router.decide = lambda q, ctx=None: {"decision": "answer", "need_id": "ح3", "segment_ids": ["ق-11"], "fit": "medium", "_meta": {}}
        assert engine.ask("هل كان الصحابة يحفظون القرآن؟")["type"] == "answer"
        # بوابة «لا يجيب عن»: سؤال يطابق حدود المقطع يُمتنع عنه مهما قال النموذج
        router.decide = lambda q, ctx=None: {"decision": "answer", "need_id": "ح7", "segment_ids": ["ق-23"], "fit": "high", "_meta": {}}
        focus.select = lambda q, segs: ({}, {"ق-23": "answers"}, {})
        r = engine.ask("ليش المسلمين يعظمون القرآن؟")
        assert r["type"] == "abstain" and r.get("gate") == "near_miss", r
    finally:
        router.decide, focus.select = orig_d, orig_s
    from app.normalize import near_duplicate
    assert near_duplicate("ليش المسلمين يعظمون القرآن؟", "لماذا يعظّم المسلمون القرآن؟")
    assert not near_duplicate("لماذا جمع عثمان القرآن؟", "كيف جمع عثمان القرآن؟")  # أداة السؤال تفرّق
    assert not near_duplicate("متى نزل القرآن؟", "كيف نزل القرآن؟")
    # البوابة لا تحجب مقطعاً عن صياغاته المعتمدة أبداً
    for s in library()["segments"]:
        for q in s["phrasings"]:
            assert not engine.near_miss(q, s), (s["id"], q)
    # مجموعة السجل: لكل مقطع منشور حالات وصول، وحالات تجنّب لما له «أسئلة قريبة»
    from app.evaluation import register_cases
    rc = register_cases()
    assert {c["target"] for c in rc if c["type"] == "reach"} == set(library()["by_id"])
    # الخادم: نقاط الكلفة محمية، والمدخلات الخاطئة 400، وحد الطلبات 429
    import os
    from starlette.testclient import TestClient
    from app import server
    os.environ.pop("DALEEL_ADMIN_KEY", None)
    c = TestClient(server.app)
    assert c.get("/api/eval/run").status_code == 403 and c.get("/api/selftest").status_code == 403
    os.environ["DALEEL_ADMIN_KEY"] = "k-test"
    assert c.get("/api/eval/run?key=wrong").status_code == 403
    os.environ.pop("DALEEL_ADMIN_KEY")
    assert c.post("/api/ask", content="not json").status_code == 400
    assert c.post("/api/ask", json={"question": "ما", "context": "x"}).status_code == 200
    server._hits.clear()
    codes = [c.post("/api/ask", json={"question": "كيف جمع القرآن"}).status_code for _ in range(server.RATE_PER_MIN + 1)]
    assert codes[-1] == 429 and codes[0] == 200, codes
    server._hits.clear()
    # سؤال غير ديني يُلتقط دون نموذج
    assert engine.ask("كيف أطبخ الكبسة؟", use_llm=False)["reason"] == "unrelated"
    # بديل الكلمات بلا فحص للنص: يُعرض «متعلقاً» لا جواباً
    r = engine.ask("كيف حفظ الصحابة القرآن في صدورهم", use_llm=False)
    assert r["type"] != "answer" or all(sg["relation"] == "partial" for sg in r["segments"]), r
    # تعطل الفحص بعد اختيار الموجِّه: «متعلق» لا جواب
    router.decide = lambda q, ctx=None: {"decision": "answer", "need_id": "ح3", "segment_ids": ["ق-12"], "fit": "high", "_meta": {}}
    focus.select = lambda q, segs: ({}, {}, {"focus_error": "Timeout"})
    try:
        r = engine.ask("سؤال تجريبي")
        assert r["segments"][0]["relation"] == "partial", r
    finally:
        router.decide, focus.select = orig_d, orig_s
    # المقاطع الحجاجية تُعرض كاملة
    assert all(library()["by_id"][i].get("no_cut") for i in ("ق-23", "ق-24", "ق-32"))
    # الآية بموضعها: نص المصحف ورابط تفسيرها، والسؤال عن معناها امتناع مع الرابط
    v = engine.ask("البقرة 255", use_llm=False)
    assert v["type"] == "verse" and v["verse"]["ref"] == "البقرة: 255" and v["verse"]["text"] == __import__("app.quran", fromlist=["x"]).verse_text(2, 255) and v["tafsir"], v
    assert engine.ask("اعرض آية الكرسي", use_llm=False)["verse"]["aya"] == 255
    t = engine.ask("ما معنى الآية 5 من سورة الفاتحة", use_llm=False)
    assert t["reason"] == "tafsir" and "1:5" in t["tafsir"]["url"], t
    assert engine.ask("كم عدد آيات سورة البقرة؟", use_llm=False)["type"] != "verse"
    # «مين كتب القرآن؟» يُستوضح بين المصدر وكتّاب الوحي
    w = engine.ask("مين كتب القرآن؟", use_llm=False)
    assert w["type"] == "clarify" and [o["id"] for o in w["options"]] == ["ح7", "ح3"] and w["template"] == "ست-05", w
    # «للتفصيل فقط»: لا يظهر ابتداءً، ويبقى في النص الكامل عند «أريد التفصيل»
    lib = library()["by_id"]
    for sid, hidden in (("ق-35", "منقولٌ بطريقِ التواتُرِ"), ("ق-03", "وقال ابنُ كثيرٍ"), ("ق-08", "كيف يأتيك الوحي")):
        rs = engine.render_segment(lib[sid])
        shown = "".join(rs["units"][i] for i in rs["focus"])
        assert hidden not in shown and hidden in rs["text"], sid
        rs = engine.render_segment(lib[sid], [i for i, u in enumerate(lib[sid]["units"]) if hidden in u])
        assert hidden not in "".join(rs["units"][i] for i in rs["focus"]), sid
    assert "الحالة الثانية" in "".join(lib["ق-08"]["units"][i] for i in lib["ق-08"]["base"])
    assert engine.render_segment(lib["ق-16"])["note"].startswith("الراجح") and engine.render_segment(lib["ق-01"])["note"] == ""
    assert "حرمة ترجمة القرآن ترجمة حرفية" in lib["ق-20"]["text"]
    print("\nكل الاختبارات نجحت" if not fails else f"\nفشل {fails}")
    return fails


if __name__ == "__main__":
    sys.exit(main())
