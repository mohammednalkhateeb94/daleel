"""قراءة سجل «دليل» وكتابته بأسماء أعمدة موحّدة، في البنيتين:

- البنية المنهجية (v21 فما بعد): «المحتوى المهيكل» و«منطق المحادثة»، وعناوين الأعمدة في صف غير الأول.
- البنية القديمة (حتى v20): «المقاطع» و«القوالب»، والعناوين في الصف الأول.

تستعمل سكربتات التصدير والنقل والتغطية الأسماء القديمة (القانونية) فقط، وهذا الملف يترجمها.
لا يغيّر أي نص؛ يقرأ الخلايا ويكتبها كما هي.
"""
from copy import copy

import openpyxl

# الاسم القانوني ← اسم الورقة في البنية المنهجية
SHEETS = {"المقاطع": "المحتوى المهيكل", "القوالب": "منطق المحادثة"}

# اسم العمود في البنية المنهجية ← الاسم القانوني
ALIASES = {
    "معرّف المحتوى (ID)": "رقم", "الحاجة (NEED_ID)": "الحاجة", "المصدر (SOURCE_ID)": "المصدر",
    "الموضع المرجعي": "الموضع", "النص المعتمد — حرفي": "النص المعتمد", "للتفصيل فقط — حرفي": "للتفصيل فقط",
    "تنبيه المراجع — حرفي": "تنبيه المراجع", "يجيب عن (ANSWERS)": "يجيب هذا المقطع عن",
    "المطابقة السلبية (NEGATIVE_MATCHES)": "أسئلة قريبة لا يجيب عنها", "المستوى العلمي الرسمي": "المستوى",
    "آيات وأحاديث للتوثيق": "آيات وأحاديث (توثيق)", "المراجع والتاريخ": "اعتمده (المراجع والتاريخ)",
    "حالة الأهلية": "صالح للنشر",
    "رمز الحاجة": "الرمز", "الحاجة — نص أصلي": "الحاجة", "صياغات المستخدم — نص أصلي": "صياغات المستخدم",
    "خارج النطاق — نص أصلي": "خارج النطاق (امتناع وإحالة)", "الخطوة التالية — نص أصلي": "الخطوة التالية",
    "الدور — نص أصلي": "الدور",
    "متى يُستخدم — نص أصلي": "متى يُستخدم", "النص الذي يراه المستخدم — حرفي": "النص الذي يراه المستخدم",
    "اعتمده — نص أصلي": "اعتمده (المراجع والتاريخ)", "ملاحظات الاعتماد — نص أصلي": "ملاحظات الاعتماد",
    # حقول المنهجية: أسماء قصيرة يقرؤها التصدير
    "المهمة الأساسية (PRIMARY_TASK)": "PRIMARY_TASK", "وظائف ثانوية (TASK_TYPES)": "TASK_TYPES",
    "المعرفة اللازمة": "KNOWLEDGE", "العمق (DEPTH)": "DEPTH", "المتطلبات السابقة (PREREQUISITES)": "PREREQUISITES",
    "مصطلحات لازمة": "TERMS", "إطار الدليل (EVIDENCE_FRAME)": "EVIDENCE_FRAME",
    "حدود الدليل (EVIDENCE_LIMITS)": "EVIDENCE_LIMITS", "لا يجيب عن (DOES_NOT_ANSWER)": "DOES_NOT_ANSWER",
    "محتوى مرتبط": "RELATED_CONTENT", "إحالة عند (REFERRAL_IF)": "REFERRAL_IF",
    "حالة النظام": "STATE", "الوظيفة المنهجية": "FUNCTION",
}
# العمود الأول الذي يُعرف به صف العناوين في كل ورقة
KEY = {"المقاطع": "رقم", "القوالب": "الرمز", "الاحتياجات": "الرمز", "المصادر": "الرقم",
       "للمراجعة": "النوع", "المرفوض": "النوع", "الناقص": "رقم"}


def _s(v):
    return "" if v is None else str(v).strip()


class Table:
    """ورقة بعناوين معروفة: صفوف بأسماء قانونية، وإضافة صف أو حذفه."""

    def __init__(self, wb, name):
        self.name = name
        self.ws = wb[SHEETS[name]] if SHEETS.get(name) in wb.sheetnames else wb[name]
        key = KEY[name]
        self.hrow = next(r for r in range(1, 8)
                         if any(ALIASES.get(_s(c.value), _s(c.value)) == key for c in self.ws[r]))
        # الأسماء المنهجية في أوراق البنية الجديدة فقط (عناوينها بعد صف العنوان والشرح)؛
        # أوراق سير العمل («للمراجعة»…) تبقى بأسمائها، ففيها «المراجع والتاريخ» بمعناه هناك.
        alias = ALIASES if self.hrow > 1 else {}
        self.cols = {}
        for c in self.ws[self.hrow]:
            h = _s(c.value)
            if h:
                self.cols.setdefault(alias.get(h, h), c.column)

    def has(self, name):
        return name in self.cols

    def rows(self):
        """صفوف البيانات: (رقم الصف، {الاسم القانوني: القيمة نصاً})."""
        out = []
        for r in range(self.hrow + 1, self.ws.max_row + 1):
            d = {n: _s(self.ws.cell(r, c).value) for n, c in self.cols.items()}
            if any(d.values()):
                out.append((r, d))
        return out

    def get(self, r, name):
        return _s(self.ws.cell(r, self.cols[name]).value) if name in self.cols else ""

    def set(self, r, name, value):
        self.ws.cell(r, self.cols[name]).value = value

    def last(self):
        r = self.ws.max_row
        while r > self.hrow and not any(_s(self.ws.cell(r, c).value) for c in self.cols.values()):
            r -= 1
        return r

    def append(self, values: dict):
        """يضيف صفاً بعد آخر صف، وينسخ تنسيق الصف السابق. الأعمدة غير المذكورة تبقى فارغة."""
        r = self.last() + 1
        src = r - 1 if r - 1 > self.hrow else None
        for name, c in self.cols.items():
            cell = self.ws.cell(r, c)
            cell.value = values.get(name)
            if src:
                s = self.ws.cell(src, c)
                cell.font, cell.alignment, cell.border, cell.fill = copy(s.font), copy(s.alignment), copy(s.border), copy(s.fill)
        if src and self.ws.row_dimensions[src].height:
            self.ws.row_dimensions[r].height = self.ws.row_dimensions[src].height
        return r


def load(path):
    return openpyxl.load_workbook(path)


def is_methodology(wb):
    return "المحتوى المهيكل" in wb.sheetnames
