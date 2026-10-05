"""ينقل البنود التي صدر فيها قرار من ورقة «للمراجعة»:

- «معتمد»        ← إلى «المقاطع» أو «القوالب»، وتُنقل ملاحظة المراجع إلى «ملاحظات الاعتماد».
- «معتمد بتعديل» ← لا يُنقل حتى يُنفَّذ التعديل في النص ويُكتب في عمود القرار «معتمد»
                    (يُذكر التعديل في الملاحظة فيُنقل معها). السكربت يطبعها لتنفيذها.
- «مرفوض»        ← إلى «المرفوض» مع السبب.

شروط النقل: اسم المراجع والتاريخ، و«موافق» من المختص الأعلم للمقطع الحساس.

    python scripts/promote.py data/register.xlsx
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from register_io import Table, is_methodology, load  # noqa: E402
from register_lib import FORM, SEG, seg_formula, style_review, style_segments  # noqa: E402


def main(path):
    wb = load(path)
    meth = is_methodology(wb)
    rev, seg, tpl, rej = (Table(wb, n) for n in ("للمراجعة", "المقاطع", "القوالب", "المرفوض"))
    moved, pending, blocked, done_rows = [], [], [], []
    for r, row in rev.rows():
        dec = row.get("القرار", "")
        if not dec:
            continue
        kind, rid, note = row.get("النوع"), row.get("الرقم"), row.get("التعديل أو الملاحظة", "")
        reviewer = row.get("المراجع والتاريخ", "")
        if dec == "معتمد بتعديل":
            pending.append(f"{rid}: {note or 'لم يُكتب التعديل'}")
            continue
        if not reviewer:
            blocked.append(f"{rid}: ينقصه اسم المراجع والتاريخ")
            continue
        if dec == "مرفوض":
            rej.append({"النوع": kind, "الرقم": rid, "الحاجة أو متى يُستخدم": row.get("الحاجة أو متى يُستخدم"),
                        "الموضع": row.get("الموضع"), "النص": row.get("النص"), "سبب الرفض": note,
                        "المراجع والتاريخ": reviewer})
            moved.append(f"{rid} ← المرفوض")
            done_rows.append(r)
            continue
        if dec != "معتمد":
            blocked.append(f"{rid}: قرار غير معروف «{dec}»")
            continue
        if kind == "مقطع":
            sp = row.get("رأي المختص الأعلم", "")
            if row.get("حساس؟") == "نعم" and sp != "موافق":
                blocked.append(f"{rid}: مقطع حساس ينقصه «موافق» من المختص الأعلم")
                continue
            notes = [x for x in [note, "مقطع حساس: وافق المختص الأعلم." if row.get("حساس؟") == "نعم" else ""] if x]
            vals = {k: row.get(k) for k in ("الأولوية", "المصدر", "الموضع", "عنوان المسألة", "السؤال في المصدر",
                                             "عبارات مشابهة", "مضمون السؤال", "يجيب هذا المقطع عن", "صياغات المستخدم",
                                             "المستوى", "حساس؟", "لا يُجتزأ", "أسئلة قريبة لا يجيب عنها",
                                             "للتفصيل فقط", "تنبيه المراجع")}
            vals.update({"رقم": rid, "الحاجة": row.get("الحاجة أو متى يُستخدم"), "النص المعتمد": row.get("النص"),
                         "آيات وأحاديث (توثيق)": row.get("آيات وأحاديث للتوثيق"),
                         "اعتمده (المراجع والتاريخ)": reviewer, "رأي المختص الأعلم": sp or None,
                         "ملاحظات الاعتماد": " ".join(notes) or "اعتُمد دون ملاحظات.",
                         "ملاحظات الاستخراج (أسباب القص)": row.get("ملاحظات الاستخراج")})
            if meth:
                vals["صالح للنشر"] = "صالح للنشر (يتحقق منه التصدير)"
            nr = seg.append(vals)
            if not meth:
                seg.ws.cell(nr, seg.cols["صالح للنشر"]).value = seg_formula(nr)
                seg.ws.cell(nr, seg.cols["صالح للنشر"]).fill = FORM
            moved.append(f"{rid} ← المقاطع" + (" (حقول المنهجية فارغة: تُملأ قبل التصدير التالي)" if meth else ""))
        else:
            tpl.append({"الرمز": rid, "متى يُستخدم": row.get("الحاجة أو متى يُستخدم"),
                        "النص الذي يراه المستخدم": row.get("النص"),
                        "مراجعة شرعية؟": "نعم" if "نعم" in str(row.get("ملاحظات الاستخراج") or "") else "لا",
                        "اعتمده (المراجع والتاريخ)": reviewer, "ملاحظات الاعتماد": note or "اعتُمد دون ملاحظات."})
            moved.append(f"{rid} ← القوالب")
        done_rows.append(r)
    for r in sorted(done_rows, reverse=True):
        rev.ws.delete_rows(r)
    style_review(rev.ws, rev.last())
    if not meth:
        style_segments(seg.ws, seg.last())
    wb.save(path)
    print(f"نُقل {len(moved)}:", *moved, sep="\n  ")
    if pending:
        print("بانتظار تنفيذ التعديل:", *pending, sep="\n  ")
    if blocked:
        print("لم يُنقل:", *blocked, sep="\n  ")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/register.xlsx")
