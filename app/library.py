"""تحميل المكتبة المصدَّرة (المقاطع المعتمدة، الاحتياجات، القوالب) مرة واحدة."""
import json
import os
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def library():
    seg = json.loads((DATA / "segments.json").read_text("utf-8"))
    needs = json.loads((DATA / "needs.json").read_text("utf-8"))
    tpl = json.loads((DATA / "templates.json").read_text("utf-8"))
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


def need_segments(need_id: str, exclude=()) -> list[dict]:
    segs = [s for s in library()["segments"] if s["need"] == need_id and s["id"] not in exclude]
    return sorted(segs, key=lambda s: (s["priority"] != "أساسي", int(s["id"].split("-")[1])))
