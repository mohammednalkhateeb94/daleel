"""جدول التغطية: لكل حاجة، ما المنشور وما في المراجعة وما الناقص من المقاطع الأساسية.

«مغطّاة» = كل مقاطعها الأساسية المخططة منشورة. «جزئياً» = بعضها. «غير مغطّاة» = لا شيء منشور.
وجود مقطع «إضافي» عن الموضوع لا يجعل الحاجة مغطّاة.

    python scripts/coverage.py data/register.xlsx   → eval/coverage.md
"""
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from register_io import Table  # noqa: E402


def rows(wb, name):
    return [d for _, d in Table(wb, name).rows()]


def main(path):
    wb = openpyxl.load_workbook(path, data_only=False)
    report = [x for x in __import__("json").loads((ROOT / "data" / "export_report.json").read_text("utf-8"))]
    published = {x["id"] for x in report if x["published"]}
    needs = [(d["الرمز"], d["الحاجة"]) for d in rows(wb, "الاحتياجات") if d.get("الرمز")]
    plan = {n: {"pub": [], "pub_extra": [], "review": [], "missing": []} for n, _ in needs}
    for d in rows(wb, "المقاطع"):
        n, core = d.get("الحاجة"), d.get("الأولوية") == "أساسي"
        if n in plan and d.get("رقم"):
            plan[n]["pub" if core and d["رقم"] in published else "pub_extra" if d["رقم"] in published else "review"].append(d["رقم"])
    for d in rows(wb, "للمراجعة"):
        if d.get("النوع") == "مقطع" and d.get("الحاجة أو متى يُستخدم") in plan and d.get("الأولوية") == "أساسي":
            plan[d["الحاجة أو متى يُستخدم"]]["review"].append(d["الرقم"])
    for d in rows(wb, "الناقص"):
        if d.get("الحاجة") in plan and d.get("الأولوية") == "أساسي":
            plan[d["الحاجة"]]["missing"].append(d["رقم"])
    out = ["# جدول التغطية", "",
           "مغطّاة = كل المقاطع الأساسية المخططة للحاجة منشورة. المقطع «الإضافي» لا يجعل الحاجة مغطّاة، ولا يُعرض عند الضغط على زرها.", "",
           "| الحاجة | الحالة | أساسي منشور | في المراجعة | ناقص | إضافي منشور |", "|---|---|---|---|---|---|"]
    for n, title in needs:
        p = plan[n]
        total = len(p["pub"]) + len(p["review"]) + len(p["missing"])
        status = "غير مغطّاة" if not p["pub"] else "مغطّاة" if len(p["pub"]) == total else "جزئياً"
        fmt = lambda xs: "، ".join(sorted(xs, key=lambda x: int(x.split("-")[1]))) or "—"
        out.append(f"| {n}: {title} | **{status}** | {fmt(p['pub'])} | {fmt(p['review'])} | {fmt(p['missing'])} | {fmt(p['pub_extra'])} |")
    (ROOT / "eval" / "coverage.md").write_text("\n".join(out) + "\n", "utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data" / "register.xlsx"))
