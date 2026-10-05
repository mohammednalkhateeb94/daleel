"""الموجِّه: النموذج اللغوي يختار ولا يكتب. يرى أوصاف المقاطع المعتمدة فقط، ويعيد قراراً مقيداً عبر أداة."""
import json
import os
import time

import httpx

from .library import library

API = "https://api.anthropic.com/v1/messages"
MODEL = os.getenv("DALEEL_MODEL", "claude-haiku-4-5-20251001")
# أسعار تقريبية لكل مليون رمز (دولار) لحساب الكلفة في السجل؛ تُضبط من متغيرات البيئة
PRICE_IN = float(os.getenv("DALEEL_PRICE_IN", "1.0"))
PRICE_OUT = float(os.getenv("DALEEL_PRICE_OUT", "5.0"))

REASONS = ["level_c", "fatwa", "hadith_request", "verse_check", "tafsir", "qiraat", "scientific",
           "off_topic", "unrelated", "not_covered", "non_arabic"]

TOOL = {
    "name": "decide",
    "description": "سجّل قرار التوجيه لسؤال المستخدم.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["answer", "clarify", "abstain"]},
            "need_id": {"type": "string", "description": "رمز الحاجة مثل ح3، أو فارغ"},
            "segment_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
            "clarify_needs": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                              "description": "الحاجات التي يُخيَّر بينها المستخدم عند الاستيضاح"},
            "abstain_reason": {"type": "string", "enum": REASONS},
            "fit": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["decision", "fit"],
    },
}


def _catalog():
    lib = library()
    lines = ["# الاحتياجات"]
    for n in lib["needs"]:
        lines.append(f"- {n['id']}: {n['title']} | صياغات: {' · '.join(n['phrasings'][:6])} | خارج النطاق: {n['out_of_scope']}")
    lines.append("\n# المقاطع المعتمدة (الوصف فقط)")
    for s in lib["segments"]:
        lines.append(f"- {s['id']} [{s['need']}، {s['priority']}]: يجيب عن: {s['about']} | سؤال المصدر: {s['src_title']}"
                     f" | عبارات: {' · '.join(s['similar'])} | صياغات: {' · '.join(s['phrasings'])}"
                     + (f" | لا يجيب عن: {' · '.join(s['not_for'])}" if s.get("not_for") else ""))
    return "\n".join(lines)


SYSTEM = """أنت موجِّه داخل «دليل»، أداة توصل المبتدئ الناطق بالعربية من سؤاله عن القرآن الكريم إلى مقطع معتمد مراجَع.
أنت لا تكتب أي إجابة ولا شرحاً؛ تختار فقط عبر الأداة decide.

القواعد:
1. answer: اختر مقطعاً أو اثنين من الفهرس يجيبان عن السؤال نفسه، لا عن موضوع قريب. لا تختر مقطعاً لسؤال مذكور أو مشابه لما في «لا يجيب عن» الخاص به. الأساسي أولاً. fit=high إن كان يجيب مباشرة، medium إن أجاب عن معظمه، low إن كان قريباً فقط.
2. clarify: إن كان السؤال يحتمل حاجتين أو أكثر من الفهرس احتمالاً متقارباً، أو كان واسعاً جداً («أخبرني عن القرآن»). اختر 2–3 حاجات.
3. abstain مع السبب:
   - fatwa: طلب حكم أو فتوى أو حالة شخصية.
   - tafsir: تفسير آية بعينها. qiraat: القراءات والأحرف. scientific: الإعجاز العلمي.
   - hadith_request: طلب نص حديث. verse_check: التحقق من نص آية.
   - off_topic: موضوع إسلامي خارج القرآن (عبادات، سيرة، فقه…).
   - unrelated: سؤال لا علاقة له بالدين أصلاً (طبخ، رياضة، تقنية، معلومات عامة…).
   - not_covered: داخل موضوع القرآن لكن لا يوجد مقطع في الفهرس يجيب عنه. لا تختر أقرب مقطع إن لم يجب فعلاً.
   - level_c: مسألة خلافية تفصيلية أو عالية الحساسية.
4. في المتابعة («ما الذي بقي؟»): لا تختر مقطعاً سبق عرضه. إن لم يوجد غيره يجيب عمّا بقي فـ abstain بسبب not_covered.
5. الصيغة العدائية أو المشككة تُعامل كسؤال حقيقي: اختر المقطع الذي يجيب عنها.
6. لا تسأل المستخدم عن دينه ولا تفترضه.
"""


def decide(question: str, ctx: dict | None = None, timeout: float = 12.0):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("no_api_key")
    ctx = ctx or {}
    user = f"سؤال المستخدم:\n{question}"
    if ctx.get("previous_question"):
        user = (f"سؤال المستخدم السابق:\n{ctx['previous_question']}\n"
                f"المقاطع التي عُرضت عليه: {', '.join(ctx.get('shown', [])) or 'لا شيء'}\n"
                f"قال إنها أجابت جزئياً، وكتب ما بقي:\n{question}")
    body = {
        "model": MODEL, "max_tokens": 300, "temperature": 0,
        "system": [{"type": "text", "text": SYSTEM}, {"type": "text", "text": _catalog(), "cache_control": {"type": "ephemeral"}}],
        "tools": [TOOL], "tool_choice": {"type": "tool", "name": "decide"},
        "messages": [{"role": "user", "content": user}],
    }
    t0 = time.time()
    r = httpx.post(API, json=body, timeout=timeout,
                   headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    r.raise_for_status()
    data = r.json()
    out = next(b["input"] for b in data["content"] if b["type"] == "tool_use")
    u = data.get("usage", {})
    tin = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    tout = u.get("output_tokens", 0)
    cost = (u.get("input_tokens", 0) + 0.1 * u.get("cache_read_input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0)) * PRICE_IN / 1e6 + tout * PRICE_OUT / 1e6
    out["_meta"] = {"model": MODEL, "latency_ms": int((time.time() - t0) * 1000), "tokens_in": tin, "tokens_out": tout, "cost_usd": round(cost, 6)}
    return out


def raw_general_answer(messages: list, timeout: float = 40.0):
    """خط الأساس «النموذج العام»: النموذج نفسه مع نصوص المكتبة كاملة، بلا فهرس احتياجات ولا فحص ولا بوابة. للتقييم فقط.
    يعيد (النص، الكلفة بالدولار، الزمن بالمللي ثانية)."""
    key = os.getenv("ANTHROPIC_API_KEY")
    lib = library()
    docs = "\n\n".join(f"[{s['id']}] {s['text']}" for s in lib["segments"])
    body = {"model": MODEL, "max_tokens": 700, "temperature": 0,
            "system": [{"type": "text", "text": "أنت مساعد يجيب عن أسئلة المبتدئين عن القرآن الكريم من هذه المصادر. اذكر رقم المقطع الذي اعتمدت عليه بين قوسين مربعين مثل [ق-12]. إن لم تجد في المصادر ما يجيب فقل ذلك.\n\n" + docs,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": messages}
    t0 = time.time()
    r = httpx.post(API, json=body, timeout=timeout,
                   headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    r.raise_for_status()
    d = r.json()
    u = d.get("usage", {})
    cost = (u.get("input_tokens", 0) + 0.1 * u.get("cache_read_input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0)) * PRICE_IN / 1e6 + u.get("output_tokens", 0) * PRICE_OUT / 1e6
    return "".join(b.get("text", "") for b in d["content"]), round(cost, 6), int((time.time() - t0) * 1000)


def catalog_json():
    return json.dumps(_catalog(), ensure_ascii=False)
