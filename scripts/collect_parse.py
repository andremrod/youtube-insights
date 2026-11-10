#!/usr/bin/env python3
"""Junta o que foi coletado no YouTube Studio em videos.json (formato único usado pelo resto da skill).

Entradas (todas opcionais, mas precisa de métricas de pelo menos uma):
  --analytics  tabela do Modo avançado:
                 • JSON {"headers": [...], "rows": ["título|duração|v1|v2|..."]} (de collect/analytics_table.js), ou
                 • CSV baixado pelo botão de download do Modo avançado (PT ou EN)
  --content    texto da página Conteúdo (get_page_text). Prefixe com o tipo: short:arquivo.txt ou video:arquivo.txt
               Traz data de publicação, descrição (gancho) e duração.
  --ids        linhas "id|data|início do título" (de collect/content_ids.js)

Uso:
  python3 collect_parse.py --analytics raw_analytics.json --content short:raw_content_shorts.txt --ids raw_ids.txt \
      --channel <canal> --collected-at 2026-11-10T13:00 --out runs/D/videos.json
Os vídeos são casados pelo início do título.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import dump_json, fold, parse_date, parse_duration, parse_number  # noqa: E402

COLUMNS = {  # chave → apelidos (fold, comparados por "começa com"); a ordem de MATCH_ORDER resolve conflitos
    "id": ["conteudo", "content", "id do video", "video id"],
    "title": ["titulo do video", "video title", "titulo", "title"],
    "published": ["horario de publicacao do video", "video publish time", "data de publicacao", "publish"],
    "duration_s": ["duracao", "duration"],
    "views": ["visualizacoes", "views"],
    "watch_h": ["tempo de exibicao", "watch time"],
    "avg_view_s": ["duracao media da visualizacao", "average view duration"],
    "avg_pct": ["porcentagem visualizada media", "average percentage viewed"],
    "subs": ["inscritos", "subscribers"],
    "impressions": ["impressoes", "impressions"],
    "ctr": ["taxa de cliques", "impressions click-through", "click-through"],
    "likes": ["marcacoes \"gostei\"", "marcacoes gostei", "gostei", "likes"],
    "comments": ["comentarios", "comments"],
    "shares": ["compartilhamentos", "shares"],
    "stayed": ["continuaram assistindo", "stayed to watch", "viewed vs. swiped", "visualizados"],
    "engaged_views": ["visualizacoes engajadas", "engaged views"],
}
MATCH_ORDER = ["avg_view_s", "avg_pct", "ctr", "stayed", "engaged_views", "watch_h", "title", "published", "duration_s",
               "views", "subs", "impressions", "likes", "comments", "shares", "id"]
PCT = {"avg_pct", "ctr", "stayed"}
DUR = {"duration_s", "avg_view_s"}
TEXT = {"id", "title", "published"}
DATE_ONLY = re.compile(r"^\d{1,2} de [a-zç]+\.? de \d{4}$", re.I)
DURATION = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
STATUS = {"publico", "public", "nao listado", "unlisted", "privado", "private", "programado", "scheduled"}


def map_header(h: str) -> str | None:
    f = fold(h).replace("(%)", "").strip()
    for key in MATCH_ORDER:
        if any(f.startswith(a) for a in COLUMNS[key]):
            return key
    return None


def convert(key: str, raw):
    if key in TEXT:
        return (raw or "").strip()
    if key in DUR:
        return parse_duration(raw)
    v = parse_number(raw)
    if v is not None and key in PCT:
        v = round(v / 100, 4)
    return v


def tkey(title: str) -> str:
    t = re.sub(r"#\w+", "", fold(title))
    return re.sub(r"[^a-z0-9]+", "", t)[:30]


def from_analytics(path: Path, ref: datetime) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    out = []
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        headers = [h for h in data["headers"] if map_header(h) not in ("duration_s", "published")]
        n = len(headers)
        for line in data["rows"]:
            if isinstance(line, str):
                sep = "\t" if "\t" in line else "|"
                parts = line.split(sep)
                # o título pode ter "|": as métricas são sempre os n últimos campos e a duração vem antes delas
                vals, dur, title = parts[-n:], parts[-n - 1], sep.join(parts[:-n - 1])
            else:
                title, dur, vals = line[0], line[1], line[2:]
            if fold(title) == "total":
                continue
            rec = {"title": title, "duration_s": parse_duration(dur)}
            for h, v in zip(headers, vals):
                k = map_header(h)
                if k:
                    rec[k] = convert(k, v)
            out.append(rec)
        return out
    rows = list(csv.reader(io.StringIO(text), csv.Sniffer().sniff(text[:4000], delimiters=",;\t")))
    hi = next(i for i, r in enumerate(rows) if sum(map_header(c) is not None for c in r) >= 3)
    headers = rows[hi]
    for r in rows[hi + 1:]:
        rec = {}
        for h, v in zip(headers, r):
            k = map_header(h)
            if k and k not in rec:
                rec[k] = convert(k, v)
        if not rec.get("title") or fold(rec.get("id", "")) == "total" or fold(rec["title"]) == "total":
            continue
        if rec.get("published"):
            dt = parse_date(rec.pop("published"), ref)
            if dt:
                rec["published_at"] = dt.isoformat(timespec="minutes")
                rec["time_known"] = dt.hour != 0 or dt.minute != 0
        out.append(rec)
    return out


def from_content(path: Path, kind: str, ref: datetime) -> list[dict]:
    lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
    starts = [i for i, l in enumerate(lines) if DURATION.match(l)]
    out = []
    for n, i in enumerate(starts):
        block = lines[i: starts[n + 1] if n + 1 < len(starts) else len(lines)]
        di = next((j for j, l in enumerate(block) if DATE_ONLY.match(fold(l))), None)
        if di is None or len(block) < 3:
            continue
        title = block[1]
        desc_lines = []
        for l in block[2:di]:
            if l in ("—", "-") or fold(l) in STATUS:
                break
            desc_lines.append(l)
        nums = [parse_number(l) for l in block[di + 1:di + 5] if parse_number(l) is not None]
        dt = parse_date(block[di], ref)
        out.append({"title": title, "description": " ".join(desc_lines), "duration_s": parse_duration(block[0]),
                    "published_at": dt.isoformat(timespec="minutes") if dt else None, "time_known": False,
                    "format": kind, "views_list": nums[0] if nums else None,
                    "comments_list": nums[1] if len(nums) > 1 else None})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analytics", action="append", default=[])
    ap.add_argument("--content", action="append", default=[], help="short:arquivo.txt ou video:arquivo.txt")
    ap.add_argument("--ids")
    ap.add_argument("--channel")
    ap.add_argument("--collected-at")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ref = datetime.fromisoformat(a.collected_at) if a.collected_at else datetime.now()

    videos: dict[str, dict] = {}
    for spec in a.content:
        kind, _, p = spec.partition(":") if ":" in spec and spec.split(":", 1)[0] in ("short", "video") else ("?", "", spec)
        for rec in from_content(Path(p), kind, ref):
            videos[tkey(rec["title"])] = rec
    for p in a.analytics:
        for rec in from_analytics(Path(p), ref):
            k = tkey(rec["title"])
            match = videos.get(k) or next((v for kk, v in videos.items() if kk[:20] == k[:20]), None)
            if match is None:
                videos[k] = rec
            else:
                full_title = match["title"] if len(match["title"]) >= len(rec["title"]) else rec["title"]
                match.update({kk: vv for kk, vv in rec.items() if vv is not None})
                match["title"] = full_title
    if a.ids:
        for line in Path(a.ids).read_text(encoding="utf-8").splitlines():
            parts = line.split("|") if "|" in line else line.split(" ", 1)
            if len(parts) < 2:
                continue
            # "id|data|título" (o título pode ter "|") ou "id título"
            rest = parts[2:] if len(parts) >= 3 and re.search(r"\d{4}", parts[1]) else parts[1:]
            vid, prefix = parts[0].strip(), "|".join(rest)
            k = tkey(prefix)
            for v in videos.values():
                if tkey(v["title"]).startswith(k[:15]) and not v.get("id"):
                    v["id"] = vid
                    break

    out = []
    for v in videos.values():
        if v.get("views") is None:
            v["views"] = v.get("views_list")
        if v.get("comments") is None:
            v["comments"] = v.get("comments_list")
        v.pop("views_list", None)
        v.pop("comments_list", None)
        if v.get("views") is None:
            continue
        v.setdefault("format", "short" if (v.get("duration_s") or 999) <= 180 else "video")
        if v["format"] == "?":
            v["format"] = "short" if (v.get("duration_s") or 999) <= 180 else "video"
        if v.get("watch_h") is not None:
            v["watch_time_s"] = v["watch_h"] * 3600
        v["id"] = v.get("id") or hashlib.sha1(v["title"].encode()).hexdigest()[:11]
        v["url"] = (f"https://www.youtube.com/shorts/{v['id']}" if v["format"] == "short" else f"https://youtu.be/{v['id']}") \
            if re.fullmatch(r"[\w-]{11}", v["id"]) else None
        v["channel"] = a.channel
        out.append(v)
    out.sort(key=lambda v: v.get("published_at") or "")
    dump_json({"channel": a.channel, "collected_at": ref.isoformat(timespec="minutes"),
               "sources": a.analytics + a.content + ([a.ids] if a.ids else []), "videos": out}, a.out)
    missing_date = sum(1 for v in out if not v.get("published_at"))
    have = sorted({k for v in out for k, val in v.items() if val is not None})
    print(f"{len(out)} vídeos → {a.out}  ({missing_date} sem data, {sum(1 for v in out if not re.fullmatch(r'[\w-]{11}', v['id']))} sem id)")
    print("campos:", ", ".join(have))
    if not out:
        sys.exit("Nenhum vídeo reconhecido.")


if __name__ == "__main__":
    main()
