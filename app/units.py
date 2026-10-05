"""تقسيم نص المقطع المعتمد إلى وحدات (جمل) مرقّمة، يختار منها «دليل» ما يجيب عن السؤال.

الشرط الأساسي: "".join(units) == text حرفياً، فلا يُعرض إلا ما في النص المعتمد.
لا يُقسم داخل آية ﴿…﴾ ولا داخل قوسين أو علامتي تنصيص، وتُدمج الوحدات القصيرة بما قبلها.
"""
import re

MIN_CHARS = 40
OPEN, CLOSE = "﴿(«\"", "﴾)»\""


def split_units(text: str) -> list[str]:
    if not text:
        return []
    cuts, depth, i, n = [], 0, 0, len(text)
    while i < n:
        c = text[i]
        if c in "﴿(«":
            depth += 1
        elif c in "﴾)»" and depth:
            depth -= 1
        if depth == 0:
            if c == "\n":
                j = i
                while j < n and text[j] in "\n \t":
                    j += 1
                cuts.append(j)
                i = j
                continue
            if c in ".؟!" and i + 1 < n and text[i + 1] in " \t":
                j = i + 1
                while j < n and text[j] in " \t":
                    j += 1
                if j < n and text[j] != "\n":
                    cuts.append(j)
                i = j
                continue
        i += 1
    bounds = [0] + [c for c in cuts if 0 < c < n] + [n]
    parts = [text[a:b] for a, b in zip(bounds, bounds[1:]) if b > a]
    units: list[str] = []
    for p in parts:
        core = p.strip()
        # وحدة قصيرة جداً أو علامة قصّ «[…]» تُلحق بما قبلها
        if units and (len(core) < MIN_CHARS or core.startswith("[…]") and len(core) < 8):
            units[-1] += p
        else:
            units.append(p)
    # إن كانت الأولى قصيرة تُلحق بالتالية
    if len(units) > 1 and len(units[0].strip()) < MIN_CHARS:
        units[1] = units[0] + units[1]
        units.pop(0)
    assert "".join(units) == text
    return units


def is_cut_marker(unit: str) -> bool:
    return bool(re.fullmatch(r"\s*\[…\]\s*", unit))
