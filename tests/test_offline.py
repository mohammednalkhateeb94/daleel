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
    sel, _ = focus.select("سؤال", [library()["by_id"]["ق-11"]])  # بلا مفتاح: يعرض كاملاً
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
    g = engine._gate({"decision": "clarify", "options": ["ح1", "ح2"]})  # كلاهما غير مغطّى: تُعرض المغطّاة
    assert g["decision"] == "clarify" and len(g["options"]) >= 2 and all(menu_segments(o) for o in g["options"]), g
    print("\nكل الاختبارات نجحت" if not fails else f"\nفشل {fails}")
    return fails


if __name__ == "__main__":
    sys.exit(main())
