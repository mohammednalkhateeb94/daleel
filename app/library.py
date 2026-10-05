"""تحميل المكتبة المصدَّرة (المقاطع المعتمدة، الاحتياجات، القوالب) مرة واحدة."""
import json
import os
from functools import lru_cache
from pathlib import Path

from .units import is_cut_marker, split_units

DATA = Path(__file__).resolve().parent.parent / "data"


def base_units(s: dict):
    """الجمل التي تُعرض ابتداءً حين حدّد المراجع جزءاً «للتفصيل فقط». None = لا حدّ."""
    detail = [" ".join(d.split()) for d in s.get("detail") or []]
    if not detail:
        return None
    def norm(u):  # علامة القص «[…]» قد تلتصق بالجملة قبلها
        return " ".join(u.replace("[…]", " ").split())
    base = [i for i, u in enumerate(s["units"]) if norm(u) and not is_cut_marker(u)
            and not any(norm(u) in d for d in detail)]
    return base or None


@lru_cache(maxsize=1)
def library():
    seg = json.loads((DATA / "segments.json").read_text("utf-8"))
    needs = json.loads((DATA / "needs.json").read_text("utf-8"))
    tpl = json.loads((DATA / "templates.json").read_text("utf-8"))
    for s in seg["segments"]:
        s["units"] = split_units(s["text"])
        s["base"] = base_units(s)
    by_id = {s["id"]: s for s in seg["segments"]}
    need_by_id = {n["id"]: n for n in needs}
    return {"meta": seg["meta"], "segments": seg["segments"], "by_id": by_id,
            "needs": needs, "need_by_id": need_by_id, "templates": tpl}


# نصوص واجهة محايدة تُعرض بدل القالب غير المعتمد في وضع الإنتاج الصارم
NEUTRAL = {
    "و-01": "«دليل» يستعين بالذكاء الاصطناعي ليختار لك نصاً من مصادر منقولة، ولا يكتب إجابات من عنده.",
    "و-02": "هل أجاب هذا عن سؤالك؟", "و-03": "ما الذي بقي دون إجابة؟", "و-04": "{يجيب_عن}",
    "و-09": "شكراً لك.", "و-10": "قد يهمك بعدها:", "و-11": "لم نتمكن من قراءة سؤالك.",
    "و-12": "لم نجد جزءاً آخر يجيب عمّا بقي من سؤالك.", "و-13": "نص الآية كما في المصحف:",
    "و-14": "نص الآية كما في المصحف:", "ست-04": "بأيّ جانب تبدأ؟", "ست-05": "ماذا تقصد بسؤالك؟",
    "ام-07": "لم نجد في مواد «دليل» ما يجيب عن هذا.", "ام-10": "خدمة فهم الأسئلة متوقفة مؤقتاً. اختر سؤالك من القائمة.",
    "ام-13": "خدمة فهم الأسئلة متوقفة مؤقتاً، فعرضنا أقرب نص بالبحث المباشر، وقد يكون أقل دقة.",
}


def T(code: str, **kw) -> str:
    """نص قالب مراجَع. في وضع الإنتاج الصارم لا يُعرض قالب غير معتمد."""
    t = library()["templates"].get(code)
    if not t or (os.getenv("DALEEL_REQUIRE_APPROVED_TEMPLATES") == "1" and t["status"] != "معتمد"):
        text = NEUTRAL.get(code, "")  # قالب غير معتمد: نص واجهة محايد لا يحمل أي حكم أو إحالة
    else:
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
