"""Funções compartilhadas: números em PT/EN, durações, datas, estatística simples. Só biblioteca padrão."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path

DASHES = {"", "-", "--", "‑‑", "—", "–", "n/a", "na", "null", "none"}

PT_MONTHS = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
             "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
             "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9,
             "out": 10, "nov": 11, "dez": 12}
EN_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
             "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
             "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
WEEKDAYS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def fold(s: str) -> str:
    """minúsculas, sem acento, espaços simples."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.replace("​", " ").replace(" ", " ")).strip().lower()


def parse_number(raw) -> float | None:
    """'1.127' → 1127, '7,3 mil' → 7300, '1,2K' → 1200, '12%' → 12, '‑‑' → None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = fold(str(raw)).replace("‑", "-")
    if s in DASHES or set(s) <= {"-", " "}:
        return None
    mult = 1.0
    for suf, m in (("mil", 1e3), ("mi", 1e6), ("k", 1e3), ("m", 1e6)):
        if re.search(rf"\d\s*{suf}$", s):
            mult, s = m, re.sub(rf"\s*{suf}$", "", s)
            break
    s = s.replace("%", "").strip()
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):          # 1.127 / 1.234.567 (milhar PT)
        s = s.replace(".", "")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+", s) and mult == 1:  # 1,127 (milhar EN)
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s) * mult
    except ValueError:
        return None


def parse_duration(raw) -> float | None:
    """'1 h 16 min' / '56 min 58 s' / '26 s' / '8 h' / '0:26' / '26' → segundos."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = fold(str(raw)).replace("‑", "-")
    if s in DASHES:
        return None
    if re.fullmatch(r"\d+(:\d{2}){1,2}", s):
        parts = [int(p) for p in s.split(":")]
        sec = 0
        for p in parts:
            sec = sec * 60 + p
        return float(sec)
    total, found = 0.0, False
    for num, unit in re.findall(r"(\d+(?:[.,]\d+)?)\s*(h|hr|hrs|hora|horas|min|m|s|seg|sec)\b", s):
        v = float(num.replace(",", "."))
        found = True
        total += v * (3600 if unit.startswith("h") else 60 if unit in ("min", "m") else 1)
    if found:
        return total
    return parse_number(s)


def parse_date(raw: str, ref: datetime, dayfirst: bool = True) -> datetime | None:
    """Datas do Meta Business Suite e dos CSVs exportados.
    'Segunda, 9 de novembro 10:49' (sem ano → ano de ref, ou ano anterior se cairia no futuro),
    '9 de novembro de 2026 10:49', 'Monday, November 9 10:49', '11/09/2026 10:49', ISO."""
    if not raw:
        return None
    s = fold(raw).replace(" as ", " ").replace(" at ", " ")
    try:
        return datetime.fromisoformat(raw.strip().replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    m = re.search(r"(\d{1,2}) de ([a-z]+)\.?(?: de (\d{4}))?,?\s*(\d{1,2}):(\d{2})", s)
    if m and m.group(2) in PT_MONTHS:
        d, mon, y, hh, mm = int(m.group(1)), PT_MONTHS[m.group(2)], m.group(3), int(m.group(4)), int(m.group(5))
        return _with_year(y, mon, d, hh, mm, ref)
    m = re.search(r"(\d{1,2}) de ([a-z]+)\.?(?: de (\d{4}))?$", s)  # só a data: "9 de nov. de 2026"
    if m and m.group(2) in PT_MONTHS:
        return _with_year(m.group(3), PT_MONTHS[m.group(2)], int(m.group(1)), 0, 0, ref)
    m = re.search(r"^([a-z]+)\.? (\d{1,2}),? (\d{4})$", s)  # "nov 9, 2026"
    if m and m.group(1) in EN_MONTHS:
        return datetime(int(m.group(3)), EN_MONTHS[m.group(1)], int(m.group(2)))
    m = re.search(r"([a-z]+)\.? (\d{1,2}),?(?: (\d{4}))?,?\s*(\d{1,2}):(\d{2})\s*(am|pm)?", s)
    if m and m.group(1) in EN_MONTHS:
        hh = int(m.group(4)) % 12 + (12 if m.group(6) == "pm" else 0) if m.group(6) else int(m.group(4))
        return _with_year(m.group(3), EN_MONTHS[m.group(1)], int(m.group(2)), hh, int(m.group(5)), ref)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4}),?\s*(\d{1,2}):(\d{2})\s*(am|pm)?", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12:
            day, month = a, b
        elif b > 12:
            month, day = a, b
        else:
            day, month = (a, b) if dayfirst else (b, a)
        hh = int(m.group(4))
        if m.group(6):
            hh = hh % 12 + (12 if m.group(6) == "pm" else 0)
        return datetime(int(m.group(3)), month, day, hh, int(m.group(5)))
    return None


def _with_year(y, mon, d, hh, mm, ref: datetime) -> datetime:
    if y:
        return datetime(int(y), mon, d, hh, mm)
    dt = datetime(ref.year, mon, d, hh, mm)
    if dt > ref.replace(hour=23, minute=59):
        dt = dt.replace(year=ref.year - 1)
    return dt


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 5:
        return None
    rx, ry = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 3) if den else None


def safe_div(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
