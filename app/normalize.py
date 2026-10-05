"""تطبيع النص العربي للمطابقة فقط (لا يُستخدم للعرض أبداً)."""
import re
import unicodedata

_DIAC = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_NON = re.compile(r"[^ء-ي0-9a-zA-Z\s]")
_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال")

STOP = set("""في من على عن الى الي ما ماذا هل كيف لماذا لم لا و او ثم ان انه هو هي هذا هذه ذلك التي الذي
مع قد كان عند كل اي اين متى يا شو ايش وش ليش مين""".split())


def norm(text: str) -> str:
    s = _DIAC.sub("", unicodedata.normalize("NFKC", text or ""))
    s = s.replace("ـ", "").translate(_MAP)
    s = _NON.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def stem(word: str) -> str:
    for p in _PREFIXES:
        if word.startswith(p) and len(word) - len(p) >= 3:
            return word[len(p):]
    if len(word) > 4 and word[0] in "وفب" and word[1:3] == "ال":
        return word[3:]
    return word


def tokens(text: str, drop_stop: bool = True) -> list[str]:
    out = []
    for w in norm(text).split():
        if drop_stop and w in STOP:
            continue
        out.append(stem(w))
    return out


# أدوات السؤال تبقى في المقارنة لأنها تفرّق المعنى («متى نزل؟» غير «كيف نزل؟»)، وتوحَّد لهجاتها
_QMAP = {"ليش": "لماذا", "ليه": "لماذا", "مين": "من", "شو": "ما", "ايش": "ما", "وش": "ما", "ماذا": "ما", "وين": "اين"}
_KEEP = {"ما", "من", "متي", "كيف", "لماذا", "هل", "كم", "اين", "اي"}
_GENERIC = {"قران", "كريم", "الله", "نبي", "محمد", "تعالي"}
_SUF = ("ون", "ين", "ات", "ها", "هم", "ه")


def _light(w: str) -> str:
    for s in _SUF:
        if len(w) - len(s) >= 3 and w.endswith(s):
            return w[:-len(s)]
    return w


def question_key(text: str) -> set[str]:
    """مفاتيح السؤال للمقارنة بـ«أسئلة قريبة لا يجيب عنها»: أداة السؤال + الكلمات الدالة، بلا الكلمات العامة في كل الأسئلة."""
    out = set()
    for w in norm(text).split():
        w = _QMAP.get(w, w)
        if w in _KEEP:
            out.add(w)
        elif w not in STOP:
            w = stem(w)
            if w not in _GENERIC and len(w) > 1:
                out.add(_light(w))
    return out


def near_duplicate(a: str, b: str, threshold: float = 0.75) -> bool:
    ka, kb = question_key(a), question_key(b)
    content = (ka | kb) - _KEEP
    if not content:
        return False
    return len(ka & kb) / len(ka | kb) >= threshold


def arabic_ratio(text: str) -> float:
    letters = [c for c in unicodedata.normalize("NFKC", text or "") if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "؀" <= c <= "ۿ") / len(letters)
