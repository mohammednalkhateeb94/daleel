"""يحوّل سجل المقاطع (Excel) إلى ملفات البيانات التي يقرؤها المنتج.

يعيد فحص شروط النشر بنفسه ولا يعتمد على نتائج معادلات Excel.
لا يُصدَّر إلا المقطع الذي يجتاز كل الشروط، وتُكتب أسباب الاستبعاد في data/export_report.json.

    python scripts/export_register.py data/register.xlsx
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.normalize import norm  # noqa: E402
from app.quran import _load, sura_name, verse_text  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
from register_io import Table  # noqa: E402

VERSE_RE = re.compile(r"﴿([^﴾]+)﴾\s*\[([^\]:]+):\s*([\d٠-٩]+)(?:\s*[-–]\s*([\d٠-٩]+))?\]")
AR_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def sura_by_name(name: str) -> int:
    n = norm(name)
    for s in range(1, 115):
        if norm(sura_name(s)) == n:
            return s
    raise ValueError(f"اسم سورة غير معروف: {name}")


def official_span(fragment: str, s: int, a: int) -> tuple[str, bool]:
    """يعيد نص الجزء المقتبس من نص المصحف المعتمد، أو الآية كاملة إن تعذّرت المحاذاة."""
    hafs, _, flat, _ = _load()
    simple_words = next(w for (ss, aa, w) in flat if ss == s and aa == a)
    off = [w for w in verse_text(s, a).split() if w not in ("۞", "۩")]  # علامات الحزب والسجدة ليست كلمات
    frag = norm(fragment).split()
    if len(off) == len(simple_words):
        for j in range(len(simple_words) - len(frag) + 1):
            if simple_words[j:j + len(frag)] == frag:
                return " ".join(off[j:j + len(frag)]), len(frag) == len(simple_words)
    return verse_text(s, a), True


def replace_verses(text: str, issues: list) -> tuple[str, list]:
    refs = []

    def sub(m):
        frag, sname, a1 = m.group(1), m.group(2).strip(), int(m.group(3).translate(AR_DIG))
        try:
            s = sura_by_name(sname)
        except ValueError as e:
            issues.append(str(e))
            return m.group(0)
        span, full = official_span(frag, s, a1)
        refs.append({"sura": s, "aya": a1, "sura_name": sura_name(s), "full": full})
        return f"﴿{span}﴾ [{sura_name(s)}: {a1}]"

    return VERSE_RE.sub(sub, text), refs


METH = ("PRIMARY_TASK", "TASK_TYPES", "KNOWLEDGE", "DEPTH", "EVIDENCE_FRAME", "EVIDENCE_LIMITS",
        "DOES_NOT_ANSWER", "RELATED_CONTENT", "REFERRAL_IF")


def cell(ws, r, c):
    v = ws.cell(r, c).value
    return "" if v is None else str(v).strip()


def main(path):
    wb = openpyxl.load_workbook(path)
    # المصادر
    src = {}
    for _, d in Table(wb, "المصادر").rows():
        if d["الرقم"]:
            src[d["الرقم"]] = dict(id=d["الرقم"], title=d["العنوان"], org=d["الجهة"], url=d["الرابط"],
                                   role=d["الدور"], approved=d["معتمد؟"])
    # الاحتياجات
    needs = []
    for _, d in Table(wb, "الاحتياجات").rows():
        if d["الرمز"]:
            needs.append(dict(id=d["الرمز"], section=d["القسم"], title=d["الحاجة"],
                              # «[فجوة]»: حاجة حقيقية غير مغطاة؛ تبقى في التصنيف ولا تُصدَّر للموجّه أمثلةً للحاجة
                              phrasings=[p.strip(" «»") for p in d["صياغات المستخدم"].split("·")
                                         if p.strip() and "[فجوة]" not in p],
                              out_of_scope=d["خارج النطاق (امتناع وإحالة)"],
                              next=[x.strip() for x in d["الخطوة التالية"].replace("·", " ").split() if x.strip().startswith("ح")],
                              entry=re.findall(r"ق-\d+", d.get("مقطع الزر", ""))))
    # المقاطع
    st = Table(wb, "المقاطع")
    hdr = st.cols
    segs, report = [], []
    for r, row in st.rows():
        g = lambda r_, name: row.get(name, "")  # noqa: E731
        sid = g(r, "رقم")
        if not sid:
            continue
        why = []
        text = g(r, "النص المعتمد")
        level, sens = g(r, "المستوى"), g(r, "حساس؟")
        s = src.get(g(r, "المصدر"))
        if not text:
            why.append("لم يُستخرج")
        if level not in ("أ", "ب"):
            why.append(f"المستوى «{level}» لا يُنشر")
        if not s or s["role"] != "معروضة" or s["approved"] != "نعم" or s["title"].startswith("[") or s["url"].startswith("["):
            why.append("المصدر غير معتمد أو غير محدد")
        for f in ("الحاجة", "الموضع", "يجيب هذا المقطع عن", "حساس؟"):
            if not g(r, f):
                why.append(f"ناقص: {f}")
        if not g(r, "اعتمده (المراجع والتاريخ)"):
            why.append("المراجعة غير موثقة")
        if sens == "نعم" and g(r, "رأي المختص الأعلم") != "موافق":
            why.append("بانتظار موافقة المختص الأعلم")
        if why:
            report.append({"id": sid, "published": False, "why": why})
            continue
        issues = []
        shown_text, verses = replace_verses(text, issues)
        src_q, q_verses = replace_verses(g(r, "السؤال في المصدر"), issues)
        # «للتفصيل فقط»: عبارات حرفية من النص لا تظهر إلا عند «أريد التفصيل»
        detail = [x.strip() for x in g(r, "للتفصيل فقط").split("|") if x.strip()] if "للتفصيل فقط" in hdr else []
        detail_shown = [replace_verses(x, [])[0] for x in detail]
        issues += [f"«للتفصيل فقط» ليس في النص: {x[:40]}…" for x, y in zip(detail, detail_shown) if y not in shown_text]
        detail = detail_shown
        if issues:
            report.append({"id": sid, "published": False, "why": issues})
            continue
        segs.append(dict(
            id=sid, need=g(r, "الحاجة"), priority=g(r, "الأولوية"), level=level, sensitive=sens == "نعم",
            source={k: s[k] for k in ("id", "title", "org", "url")},
            location=re.sub(r"\s*—?\s*https?://\S+", "", g(r, "الموضع")).strip(),
            link=(re.search(r"https?://\S+", g(r, "الموضع")) or re.search(r".*", s["url"])).group(0),
            src_title=g(r, "عنوان المسألة"), src_question=src_q,
            similar=[x.strip() for x in g(r, "عبارات مشابهة").split("|") if x.strip()],
            gist="" if g(r, "مضمون السؤال") in ("", "—") else g(r, "مضمون السؤال"),
            text=shown_text, verses=verses + q_verses, about=g(r, "يجيب هذا المقطع عن"),
            phrasings=[x.strip() for x in g(r, "صياغات المستخدم").split("|") if x.strip()],
            reviewer=g(r, "اعتمده (المراجع والتاريخ)"), approval_note=g(r, "ملاحظات الاعتماد"),
            no_cut=hdr.get("لا يُجتزأ") is not None and g(r, "لا يُجتزأ") == "نعم",
            not_for=[x.strip() for x in g(r, "أسئلة قريبة لا يجيب عنها").split("|") if x.strip()]
            if "أسئلة قريبة لا يجيب عنها" in hdr else [],
            detail=detail, note=g(r, "تنبيه المراجع") if "تنبيه المراجع" in hdr else ""))
        # حقول المنهجية (البنية المنهجية فقط): يقرؤها المحرك للتسجيل والبوابات، ولا تُعرض للمستخدم
        meth = {k: g(r, k) for k in METH if k in hdr and g(r, k) not in ("", "—")}
        if meth:
            segs[-1]["method"] = meth
        report.append({"id": sid, "published": True, "verses": verses + q_verses})
    # القوالب: المعتمد من «القوالب»، والمسودات من «للمراجعة» (تُعرض في وضع التطوير فقط)
    tpl = {}
    for _, d in Table(wb, "للمراجعة").rows():
        if d["النوع"] == "قالب" and d["الرقم"]:
            tpl[d["الرقم"]] = dict(when=d["الحاجة أو متى يُستخدم"], text=d["النص"], status="مسودة")
    for _, d in Table(wb, "القوالب").rows():
        if d["الرمز"]:
            tpl[d["الرمز"]] = dict(when=d["متى يُستخدم"], text=d["النص الذي يراه المستخدم"], status="معتمد")
    out = ROOT / "data"
    meta = {"library_version": date.today().isoformat(), "segments": len(segs),
            "source_file": Path(path).name}
    (out / "segments.json").write_text(json.dumps({"meta": meta, "segments": segs}, ensure_ascii=False, indent=1), "utf-8")
    (out / "needs.json").write_text(json.dumps(needs, ensure_ascii=False, indent=1), "utf-8")
    (out / "templates.json").write_text(json.dumps(tpl, ensure_ascii=False, indent=1), "utf-8")
    (out / "export_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    pub = sum(1 for x in report if x["published"])
    print(f"نُشر {pub} مقطعاً، واستُبعد {len(report) - pub}. القوالب: {len(tpl)}.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data" / "register.xlsx"))
