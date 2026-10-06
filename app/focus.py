"""الفحص والتركيز بعد اختيار المقطع، في استدعاء واحد. النموذج لا يكتب نصاً:

1. الحكم: هل نص المقطع يجيب عن السؤال نفسه؟ يجيب / متعلق جزئياً / لا يجيب. «لا يجيب» يُسقط المقطع.
2. التركيز: أرقام الجمل التي تجيب، فيُعرض المختار حرفياً وبقية النص بزر «أريد التفصيل».
عند أي خطأ يبقى المقطع كما اختاره الموجِّه ويُعرض كاملاً.
"""
import os
import re
import time

import httpx

from .router import API, MODEL, PRICE_IN, PRICE_OUT
from .units import is_cut_marker

MAX_SHARE = 0.75  # إن غطّى المختار أكثر من هذا من النص يُعرض كاملاً

TOOL = {
    "name": "check_and_select",
    "description": "احكم على كل مقطع هل يجيب عن سؤال المستخدم، واختر أرقام الجمل التي تجيب.",
    "input_schema": {
        "type": "object",
        "properties": {
            "segments": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"},
                "verdict": {"type": "string", "enum": ["answers", "partial", "none"]},
                "whole": {"type": "boolean", "description": "true إن كان السؤال يحتاج المقطع كله"},
                "units": {"type": "array", "items": {"type": "integer"}, "maxItems": 4},
                "missing": {"type": "string", "description": "للحكم partial فقط: العنصر المطلوب في السؤال الذي لا يجيب عنه النص؛ فارغ لغيره"},
            }, "required": ["id", "verdict", "whole", "units", "missing"]}},
        },
        "required": ["segments"],
    },
}

SYSTEM = """أنت جزء من «دليل»، أداة تعرض على المبتدئ نصاً معتمداً يجيب عن سؤاله عن القرآن.
لا تكتب أي نص. احكم على كل مقطع، واختر أرقام الجمل منه.

الحكم (verdict) بقراءة نص المقطع نفسه، لا موضوعه العام. مع كل مقطع بطاقة كتبها المراجع: «يجيب عن» (ANSWERS)، و«حدود الدليل» (EVIDENCE_LIMITS)، و«لا يجيب عن» (DOES_NOT_ANSWER)، و«أسئلة قريبة لا يجيب عنها». ومع السؤال وظيفته (TASK) ومسألته الدقيقة (ISSUE) إن وُجدتا.

الخطوة 1 — عناصر الطلب: حدّد ما يطلبه المستخدم فعلاً، صراحة أو دلالة، من نص السؤال ووظيفته ومسألته الدقيقة. هذه وحدها عناصر الطلب؛ ما يتصل بالموضوع ولم يُطلب ليس منها.

الخطوة 2 — الحكم:
- answers: النص يجيب المسألة المطلوبة نفسها. هذا هو الحكم الأصل متى أجاب النص عن عناصر الطلب، ولو لم يستوعب كل تفاصيل الموضوع.
- partial: فقط إن اجتمعت ثلاثة شروط:
  1) النص يجيب جزءاً معتبراً من سؤال المستخدم؛
  2) ويوجد عنصر من عناصر الطلب (الخطوة 1) لا يجيب عنه النص؛
  3) وهذا النقص يدعمه ما في «حدود الدليل» أو «لا يجيب عن».
  وحينها اكتب في missing هذا العنصر المطلوب كما في السؤال. إن لم تستطع تسمية عنصر مطلوب فعلاً لا يجيب عنه النص، فالحكم answers.
- none: موضوعه قريب لكنه لا يؤدي المهمة المطلوبة أصلاً. مثال: السؤال عن «متى» شيء والنص عن «كيف» شيء آخر، أو السؤال عن نزول القرآن والنص عن حفظه، أو السؤال عن تعريف أو مكانة والنص عن دليل.
- إن كان السؤال من جنس «أسئلة قريبة لا يجيب عنها» فالحكم none.

قواعد البطاقة:
- وجود «حدود الدليل» أو «لا يجيب عن» في البطاقة ليس بذاته سبباً للحكم partial. كل مقطع له حدود؛ قارن الحدود بعناصر الطلب الفعلية، لا بحدود الموضوع العامة.
- حدٌّ يخص جانباً لم يطلبه المستخدم لا يدخل في الحكم.
- وجود معلومات مرتبطة بالسؤال في النص لا يجعله answers إذا كان المطلوب نفسه خارج حدوده.
- البطاقة تفرّق بين answers وpartial؛ لا تجعل المقطع none بسببها وحدها ما دام النص يجيب جزءاً معتبراً من المطلوب.
- قارن بالمعنى لا باللفظ: الطلب قد يُصاغ بكلمات غير كلمات البطاقة.
عند التردد بين partial وnone اختر none: الامتناع أسلم من عرض نص لا يجيب.
الصيغة المشككة أو العدائية تُعامل كسؤال حقيقي: احكم على ما يجيب عنه النص من مضمونها.

اختيار الجمل (للمقطع الذي حكمه answers أو partial):
1. اختر أقل عدد من الجمل يجيب عن السؤال نفسه إجابة كاملة مفهومة وحدها (غالباً 1–3).
2. إن كانت الجملة المختارة لا تُفهم دون جملة قبلها (مثل عنوان قائمة، أو «ومنها»، أو ضمير يعود على ما قبله) فاختر تلك الجملة معها.
3. لا تختر قولاً أو اعتراضاً دون الجملة التي فيها الجواب أو الترجيح.
4. whole=true إن كان السؤال عاماً عن موضوع المقطع كله، أو كان كل المقطع جواباً واحداً متصلاً.
"""


LIST_ITEM = re.compile(r"^\s*(\d+|[أ-ي])\s*[)\-–.]")


def _with_headers(units, idx):
    """يضيف رأس القائمة أو الجملة المنتهية بنقطتين التي تُفهم الجملة المختارة بها (مثل «منها:» قبل بنود مرقّمة)."""
    out = set(idx)
    for i in idx:
        j = i - 1
        while j >= 0 and LIST_ITEM.match(units[j]) and not units[j].rstrip().endswith(":"):
            j -= 1
        if j >= 0 and units[j].rstrip().endswith(":") and (j == i - 1 or LIST_ITEM.match(units[i])):
            out.add(j)
    return sorted(out)


def _numbered(seg):
    lines = "\n".join(f"[{i}] {u.strip()}" for i, u in enumerate(seg["units"]) if not is_cut_marker(u))
    return _card(seg) + lines


def _task_line(task, issue):
    parts = [f"وظيفة السؤال (TASK): {task}" if task else "", f"المسألة الدقيقة (ISSUE): {issue}" if issue else ""]
    return "".join(x + "\n" for x in parts if x)


def _card(seg):
    """بطاقة المراجع للمقطع: يجيب عن، وحدود الدليل، ولا يجيب عن، والأسئلة القريبة التي لا يجيب عنها."""
    m = seg.get("method") or {}
    rows = [("يجيب عن", seg.get("about", "")), ("حدود الدليل", m.get("EVIDENCE_LIMITS", "")),
            ("لا يجيب عن", m.get("DOES_NOT_ANSWER", "")),
            ("أسئلة قريبة لا يجيب عنها", " · ".join(seg.get("not_for") or []))]
    return "".join(f"({k}: {v})\n" for k, v in rows if v)


def select(question: str, segs: list[dict], timeout: float = 8.0, task: str = "", issue: str = ""):
    """يعيد ({id: [أرقام] أو None}, {id: الحكم}, meta). None = اعرض المقطع كاملاً. لا حكم = لم يُفحص."""
    out = {s["id"]: None for s in segs}
    verdicts = {}
    cand = list(segs)
    key = os.getenv("ANTHROPIC_API_KEY")
    if not cand or not key or not question.strip():
        return out, verdicts, {}
    docs = "\n\n".join(f"<مقطع id=\"{s['id']}\">\n{_numbered(s)}\n</مقطع>" for s in cand)
    body = {"model": MODEL, "max_tokens": 500, "temperature": 0, "system": SYSTEM,
            "tools": [TOOL], "tool_choice": {"type": "tool", "name": "check_and_select"},
            "messages": [{"role": "user", "content": f"سؤال المستخدم:\n{question}\n{_task_line(task, issue)}\n{docs}"}]}
    t0 = time.time()
    try:
        r = httpx.post(API, json=body, timeout=timeout,
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return out, verdicts, {"focus_error": type(e).__name__}
    picked = next((b["input"] for b in data["content"] if b["type"] == "tool_use"), {})
    missing = {}
    by_id = {s["id"]: s for s in cand}
    for p in picked.get("segments", []):
        s = by_id.get(p.get("id"))
        if not s:
            continue
        if p.get("verdict") in ("answers", "partial", "none"):
            verdicts[s["id"]] = p["verdict"]
            # PARTIAL يحتاج عنصراً مطلوباً مسمّى لا يجيب عنه النص؛ بلا تسمية فهو جواب
            if p["verdict"] == "partial" and not str(p.get("missing") or "").strip():
                verdicts[s["id"]] = "answers"
            elif p["verdict"] == "partial":
                missing[s["id"]] = str(p["missing"]).strip()[:200]
        if p.get("whole") or p.get("verdict") == "none" or len(s["units"]) < 3 or s.get("no_cut"):
            continue
        idx = sorted({i for i in p.get("units", []) if isinstance(i, int) and 0 <= i < len(s["units"])
                      and not is_cut_marker(s["units"][i])})
        if not idx:
            continue
        idx = _with_headers(s["units"], idx)
        if len(s["units"]) - len(idx) <= 1:
            continue  # لم يبق إلا جملة واحدة: يُعرض كاملاً
        share = sum(len(s["units"][i]) for i in idx) / max(1, len(s["text"]))
        if share <= MAX_SHARE:
            out[s["id"]] = idx
    u = data.get("usage", {})
    cost = u.get("input_tokens", 0) * PRICE_IN / 1e6 + u.get("output_tokens", 0) * PRICE_OUT / 1e6
    return out, verdicts, {"partial_missing": missing, "focus_ms": int((time.time() - t0) * 1000), "focus_cost_usd": round(cost, 6)}
