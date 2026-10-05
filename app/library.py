"""تحميل المكتبة المصدَّرة (المقاطع المعتمدة، الاحتياجات، القوالب) مرة واحدة."""
import json
import os
from functools import lru_cache
from pathlib import Path

from .units import split_units

DATA = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def library():
    seg = json.loads((DATA / "segments.json").read_text("utf-8"))
    needs = json.loads((DATA / "needs.json").read_text("utf-8"))
    tpl = json.loads((DATA / "templates.json").read_text("utf-8"))
    for s in seg["segments"]:
        s["units"] = split_units(s["text"])
    by_id = {s["id"]: s for s in seg["segments"]}
    need_by_id = {n["id"]: n for n in needs}
    return {"meta": seg["meta"], "segments": seg["segments"], "by_id": by_id,
            "needs": needs, "need_by_id": need_by_id, "templates": tpl}


def T(code: str, **kw) -> str:
    """نص قالب مراجَع. في وضع الإنتاج الصارم لا يُعرض قالب غير معتمد."""
    t = library()["templates"].get(code)
    if not t:
        return ""
    if os.getenv("DALEEL_REQUIRE_APPROVED_TEMPLATES") == "1" and t["status"] != "معتمد":
        return ""
    text = t["text"]
    for k, v in kw.items():
        text = text.replace("{" + k + "}", v)
    return text


def menu_segments(need_id: str, exclude=()) -> list[dict]:
    """مقاطع زر الحاجة: المحددة له في السجل («مقطع الزر») بترتيبها، وإلا المقاطع الأساسية فقط.
    مقطع «إضافي» لا يُعرض جواباً لعنوان الحاجة لأنه يجيب عن جانب منها لا عنها."""
    lib = library()
    n = lib["need_by_id"].get(need_id, {})
    if n.get("entry"):
        segs = [lib["by_id"][i] for i in n["entry"] if i in lib["by_id"]]
    else:
        segs = [s for s in need_segments(need_id) if s["priority"] == "أساسي"]
    return [s for s in segs if s["id"] not in exclude]


def need_segments(need_id: str, exclude=()) -> list[dict]:
    segs = [s for s in library()["segments"] if s["need"] == need_id and s["id"] not in exclude]
    return sorted(segs, key=lambda s: (s["priority"] != "أساسي", int(s["id"].split("-")[1])))
