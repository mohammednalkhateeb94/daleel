"""فحص بقواعد ثابتة قبل استدعاء النموذج: يلتقط ما يجب الامتناع عنه أو التعامل معه بطريقة خاصة."""
import re

from .normalize import arabic_ratio, norm
from .quran import find_ref, find_verse, sura_name, verse_text

def _rx(*words):
    return re.compile("|".join(words))

FATWA = _rx(r"\bهل يجوز", r"\bما حكم", r"\bحكم (لمس|قراءه|قراءة|تلاوه|ترك|من)", r"\bيجوز لي", r"\bحلال\b", r"\bحرام\b",
            r"\bهل علي\b", r"\bهل اثم", r"\bكفاره", r"\bافتني", r"\bفتوى")
HADITH = _rx(r"(اعطني|هات|اذكر|ارسل|اريد|ابي|ابغى|عطني|انقل لي).{0,15}حديث", r"\bما صحه حديث", r"\bهل (هذا )?حديث\b", r"\bحديث (صحيح|ضعيف) عن")
QIRAAT = _rx(r"\bالقراءات\b", r"\bالاحرف السبعه", r"\bقراءه (ورش|حفص|قالون)", r"\bالقراءات العشر", r"\bرواية (ورش|حفص)", r"\bروايه (ورش|حفص)")
SCI = _rx(r"اعجاز علمي", r"الاعجاز العلمي", r"العلم الحديث", r"\bعلميا\b", r"اكتشاف(ات)? علميه")
TAFSIR = _rx(r"\bتفسير (ايه|اية|قوله|سوره)", r"\bما معني (ايه|قوله)", r"\bفسر لي", r"\bاشرح (لي )?(ايه|قوله|سوره)", r"\bمعني قوله تعالي")
WHO_WROTE = re.compile(r"\b(من|مين)\s+(اللي\s+|الذي\s+)?(كتب|الف|صنف)\s+(هذا\s+)?القران\b")
# أسئلة لا علاقة لها بالدين (للمسار بلا نموذج؛ الموجِّه يلتقط غيرها)
UNRELATED = _rx(r"\bاطبخ", r"\bطبخ", r"\bوصفه\b", r"\bكبسه\b", r"\bمباراه\b", r"كاس العالم", r"\bالدوري\b",
                r"\bالطقس\b", r"\bسعر\b", r"\bبرمجه\b", r"\bعاصمه\b", r"\bفيلم\b", r"\bمسلسل\b")
OFF_TOPIC = _rx(r"صلاه", r"\bاصلي\b", r"\bنصلي\b", r"صيام", r"\bاصوم\b", r"\bرمضان\b", r"زكاه", r"\bالحج\b", r"\bالعمره\b", r"وضوء", r"\bاتوضا\b",
                r"\bالسيره\b", r"\bالطلاق\b", r"\bالميراث\b", r"\bالحجاب\b", r"\bالزواج\b")


def precheck(question: str):
    q = (question or "").strip()
    n = norm(q)
    if len(n) < 3 or not re.search(r"[ء-يa-zA-Z]{2}", n):
        return {"decision": "invalid"}
    if arabic_ratio(q) < 0.4:
        return {"decision": "abstain", "reason": "non_arabic"}
    if HADITH.search(n):
        return {"decision": "abstain", "reason": "hadith_request"}
    if FATWA.search(n):
        return {"decision": "abstain", "reason": "fatwa"}
    # آية مكتوبة في السؤال: بين أقواس أو نص طويل يطابق آية
    quoted = re.findall(r"[﴿{«\"](.+?)[﴾}»\"]", q)
    candidates = quoted or ([q] if len(n.split()) >= 5 else [])
    cue = bool(re.search(r"قال تعالي|قوله تعالي|قال الله|يقول الله|\bايه\b|\bاية\b", n))
    for c in candidates:
        v = find_verse(c, min_ratio=0.6 if (quoted and cue) else 0.72 if quoted else 0.8)
        if v:
            if TAFSIR.search(n) or re.search(r"\bمعني\b|\bتفسير\b", n):
                return {"decision": "abstain", "reason": "tafsir", "verse": v}
            return {"decision": "verse", "verse": v}
    if quoted and re.search(r"\bايه\b|\bاية\b|قال تعالي|قوله تعالي", n):
        return {"decision": "abstain", "reason": "verse_not_found"}
    # «مين كتب القرآن؟» يحتمل المصدر (ح7) أو كتّاب الوحي (ح3): استيضاح ثابت بدل التخمين
    if WHO_WROTE.search(n):
        # ثلاثة مقاصد (القسم 18 من المنهجية): كل خيار سؤال كامل يُرسل إلى «دليل» عند اختياره
        return {"decision": "clarify", "options": ["ح7", "ح3"], "template": "ست-06",
                "ask_options": [("ست-06-1", "ح7"), ("ست-06-2", "ح3"), ("ست-06-3", "ح3")]}
    # موضع مذكور بالاسم والرقم («البقرة 255»، «آية الكرسي»): يُعرض نص الآية من المصحف، أو يُحال لتفسيرها
    ref = find_ref(q)
    if ref and ref[1]:
        sura, aya = ref
        if TAFSIR.search(n) or re.search(r"\bمعني\b|\bتفسير\b|\bفسر\b|\bاشرح\b", n):
            return {"decision": "abstain", "reason": "tafsir", "ref": ref}
        return {"decision": "verse", "verse": {"sura": sura, "aya": aya, "aya_end": aya, "exact": True,
                                                "text": verse_text(sura, aya), "ref": f"{sura_name(sura)}: {aya}",
                                                "sura_name": sura_name(sura), "lookup": True}}
    if TAFSIR.search(n):
        return {"decision": "abstain", "reason": "tafsir"}
    if QIRAAT.search(n):
        return {"decision": "abstain", "reason": "qiraat"}
    if SCI.search(n):
        return {"decision": "abstain", "reason": "scientific"}
    if UNRELATED.search(n) and "قران" not in n:
        return {"decision": "abstain", "reason": "unrelated"}
    if OFF_TOPIC.search(n) and "قران" not in n:
        return {"decision": "abstain", "reason": "off_topic"}
    return None
