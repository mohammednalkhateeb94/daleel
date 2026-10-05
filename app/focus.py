"""التركيز: يختار النموذج أرقام الجمل التي تجيب عن السؤال من المقطع المعتمد، ولا يكتب نصاً.

يُعرض المختار حرفياً، وبقية النص متاحة بزر «أريد التفصيل». عند أي خطأ يُعرض المقطع كاملاً.
"""
import os
import time

import httpx

from .router import API, MODEL, PRICE_IN, PRICE_OUT
from .units import is_cut_marker

MAX_SHARE = 0.75  # إن غطّى المختار أكثر من هذا من النص يُعرض كاملاً

TOOL = {
    "name": "select_units",
    "description": "اختر أرقام الجمل التي تجيب عن سؤال المستخدم من كل مقطع.",
    "input_schema": {
        "type": "object",
        "properties": {
            "segments": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"},
                "whole": {"type": "boolean", "description": "true إن كان السؤال يحتاج المقطع كله"},
                "units": {"type": "array", "items": {"type": "integer"}, "maxItems": 4},
            }, "required": ["id", "whole", "units"]}},
        },
        "required": ["segments"],
    },
}

SYSTEM = """أنت جزء من «دليل»، أداة تعرض على المبتدئ نصاً معتمداً يجيب عن سؤاله عن القرآن.
لا تكتب أي نص. اختر فقط أرقام الجمل من كل مقطع.

القواعد:
1. اختر أقل عدد من الجمل يجيب عن السؤال نفسه إجابة كاملة مفهومة وحدها (غالباً 1–3).
2. إن كانت الجملة المختارة لا تُفهم دون جملة قبلها (مثل عنوان قائمة، أو «ومنها»، أو ضمير يعود على ما قبله) فاختر تلك الجملة معها.
3. لا تختر قولاً أو اعتراضاً دون الجملة التي فيها الجواب أو الترجيح.
4. whole=true إن كان السؤال عاماً عن موضوع المقطع كله، أو كان كل المقطع جواباً واحداً متصلاً.
"""


def _numbered(seg):
    return "\n".join(f"[{i}] {u.strip()}" for i, u in enumerate(seg["units"]) if not is_cut_marker(u))


def select(question: str, segs: list[dict], timeout: float = 8.0):
    """يعيد ({id: [أرقام] أو None}, meta). None = اعرض المقطع كاملاً."""
    out = {s["id"]: None for s in segs}
    cand = [s for s in segs if len(s.get("units", [])) >= 3 and not s.get("no_cut")]
    key = os.getenv("ANTHROPIC_API_KEY")
    if not cand or not key or not question.strip():
        return out, {}
    docs = "\n\n".join(f"<مقطع id=\"{s['id']}\">\n{_numbered(s)}\n</مقطع>" for s in cand)
    body = {"model": MODEL, "max_tokens": 200, "temperature": 0, "system": SYSTEM,
            "tools": [TOOL], "tool_choice": {"type": "tool", "name": "select_units"},
            "messages": [{"role": "user", "content": f"سؤال المستخدم:\n{question}\n\n{docs}"}]}
    t0 = time.time()
    try:
        r = httpx.post(API, json=body, timeout=timeout,
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return out, {"focus_error": type(e).__name__}
    picked = next((b["input"] for b in data["content"] if b["type"] == "tool_use"), {})
    by_id = {s["id"]: s for s in cand}
    for p in picked.get("segments", []):
        s = by_id.get(p.get("id"))
        if not s or p.get("whole"):
            continue
        idx = sorted({i for i in p.get("units", []) if isinstance(i, int) and 0 <= i < len(s["units"])
                      and not is_cut_marker(s["units"][i])})
        if not idx:
            continue
        share = sum(len(s["units"][i]) for i in idx) / max(1, len(s["text"]))
        if share <= MAX_SHARE:
            out[s["id"]] = idx
    u = data.get("usage", {})
    cost = u.get("input_tokens", 0) * PRICE_IN / 1e6 + u.get("output_tokens", 0) * PRICE_OUT / 1e6
    return out, {"focus_ms": int((time.time() - t0) * 1000), "focus_cost_usd": round(cost, 6)}
