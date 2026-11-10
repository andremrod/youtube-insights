#!/usr/bin/env python3
"""Gera tags.json: as características de cada vídeo que a análise cruza com as métricas.

Preenche sozinho o que dá para tirar do título e da descrição: formato do título (pergunta,
"Nome: explicação", só o nome…), tipo de gancho (1ª frase da descrição), série/EP, hashtags no
título, época, região e tema (references/themes.json). Com --videos, acha o MP4 local de cada vídeo.
Depois o Claude REVISA tags.json: corrige o tema, preenche o que ficou "?" e pode acrescentar
campos livres em "extra" (ex.: "capa": "mapa").

Uso:
  python3 tag_videos.py --posts runs/D/videos.json --out runs/D/tags.json \
      [--videos "<pasta dos MP4>"] [--keep runs/ANTERIOR/tags.json]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import dump_json, fold, load_json  # noqa: E402

SKILL = Path(__file__).resolve().parent.parent


def split_caption(caption: str) -> tuple[str, list[str]]:
    tags = re.findall(r"#(\w+)", caption)
    text = re.sub(r"#\w+", "", caption).strip()
    return re.sub(r"\s+", " ", text), tags


def first_sentence(text: str) -> str:
    t = re.sub(r"^EP\.?\s*\d+\s*", "", text, flags=re.I).strip()
    # título em CAIXA ALTA antes do texto ("A NUVEM DE GÁS ... | PRIMEIRA GUERRA MUNDIAL Imagine ...")
    m = re.match(r"^([A-ZÀ-Ý0-9 ,.'|:\-–]{12,}?)\s+(?=[A-ZÀ-Ý][a-zà-ÿ])", t)
    if m:
        t = t[m.end():]
    m = re.search(r"(.+?[.!?…])(\s|$)", t)
    return (m.group(1) if m else t)[:220].strip()


def hook_type(sentence: str, text: str) -> str:
    f = fold(sentence)
    if f.startswith("imagine"):
        return "Imagine (você na cena)"
    if f.startswith(("voce sabia", "sabia que")):
        return "Você sabia?"
    if f.endswith("?") or f.startswith(("por que", "como ", "o que ", "quem ")):
        return "Pergunta"
    if re.match(r"^(em|no ano de|durante)\s+(\d{3,4}|mais de|o ano)", f) or re.match(r"^durante", f):
        return "Contexto/data"
    if f.startswith(("ele ", "ela ", "eles ", "elas ")):
        return "Mistério (quem é?)"
    return "Afirmação"


def title_format(t: str) -> str:
    f = fold(t)
    if "?" in t or f.startswith(("por que", "como ", "o que ", "quem ", "qual ")):
        return "Pergunta (POR QUE / COMO…?)"
    if ":" in t:
        return "Nome: explicação"
    if re.search(r"[—–|-]\s*\d{3,4}|\(\d{4}", t) or "|" in t:
        return "Nome + ano/série"
    return "Só o nome"


def era_from(text: str, tags: list[str]) -> str:
    years = [int(y) for y in re.findall(r"(?<!\d)(\d{3,4})(?!\d)", text + " " + " ".join(tags))
             if 100 <= int(y) <= 2030]
    if "d.C." in text or "d.c." in fold(text):
        years += [int(y) for y in re.findall(r"(\d{1,4})\s*d\.?\s?C", text)]
    if not years:
        return "?"
    y = min(years)
    if y < 500:
        return "Antiguidade"
    if y < 1500:
        return "Idade Média"
    if y < 1800:
        return "Idade Moderna"
    if y < 1914:
        return "Século XIX"
    if y <= 1945:
        return "Guerras Mundiais (1914–1945)"
    return "Pós-1945"


def theme_from(text: str, tags: list[str], themes: dict) -> str:
    hay = fold(text + " " + " ".join(tags))
    best, score = "?", 0
    for name, words in themes.items():
        s = sum(1 for w in words if fold(w) in hay)
        if s > score:
            best, score = name, s
    return best


def region_from(text: str, tags: list[str], regions: dict) -> str:
    hay = fold(text + " " + " ".join(tags))
    for name, words in regions.items():
        if name.startswith("_"):
            continue
        if any(fold(w) in hay for w in words):
            return name
    return regions.get("_default", "?") if isinstance(regions.get("_default"), str) else "?"


def scan_videos(folder: Path) -> list[dict]:
    if not shutil.which("ffprobe"):
        print("aviso: ffprobe não encontrado (brew install ffmpeg); durações ficam vazias", file=sys.stderr)
        return []
    vids = []
    for f in folder.rglob("*.mp4"):
        if any(p in f.parts for p in ("node_modules", "public", ".cache")) or "raw" in f.stem.lower():
            continue
        try:
            d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                               capture_output=True, text=True, timeout=30).stdout.strip()
            vids.append({"path": str(f), "duration_s": round(float(d), 1),
                         "mtime": datetime.fromtimestamp(f.stat().st_mtime),
                         "tokens": set(re.findall(r"[a-z0-9]{3,}", fold(f.parent.parent.name + " " + f.stem)))})
        except (ValueError, subprocess.TimeoutExpired):
            continue
    return vids


STOP = {"reels", "por", "que", "como", "comecou", "dos", "das", "the", "out", "raw", "mp4"}


def post_tokens(text: str, tags: list[str]) -> set[str]:
    hay = set(re.findall(r"[a-z0-9]{3,}", fold(text + " " + " ".join(tags))))
    for tag in tags:  # #UniaoSovietica → uniao, sovietica; #Chernobyl1986 → chernobyl, 1986
        parts = re.findall(r"[A-Z]?[a-zà-ÿ]+|\d+", tag)
        hay |= {fold(x) for x in parts if len(x) >= 3}
    return hay


def assign_videos(posts: list[dict], texts: dict, vids: list[dict]) -> dict:
    """Casa cada post com um vídeo: palavras raras em comum (peso IDF) e proximidade da data.
    Cada vídeo vai para um post só."""
    import math
    df: dict[str, int] = {}
    for v in vids:
        for tok in v["tokens"] - STOP:
            df[tok] = df.get(tok, 0) + 1
    cands = []
    for p in posts:
        pub = datetime.fromisoformat(p["published_at"])
        if not p.get("time_known", True):
            pub = pub.replace(hour=23, minute=59)  # só a data: aceita arquivos do mesmo dia
        hay = post_tokens(*texts[p["id"]])
        for i, v in enumerate(vids):
            common = (v["tokens"] - STOP) & hay
            if p.get("duration_s") and abs(v["duration_s"] - p["duration_s"]) > 1.5:
                continue  # a duração do YouTube (arredondada ao segundo) tem que bater com o MP4
            dt = (pub - v["mtime"]).total_seconds() / 3600
            if not common or dt < -0.1 or dt > 72:
                continue
            w = sum(math.log(1 + len(vids) / df[t]) for t in common)
            cands.append((w / (1 + dt / 12), p["id"], i))
    used_p, used_v, out = set(), set(), {}
    for score, pid, i in sorted(cands, reverse=True):
        if pid in used_p or i in used_v:
            continue
        used_p.add(pid); used_v.add(i); out[pid] = vids[i]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--posts", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--videos", help="pasta com os MP4 publicados (para duração e retenção)")
    ap.add_argument("--themes", default=str(SKILL / "references" / "themes.json"))
    ap.add_argument("--keep", help="tags.json de rodada anterior para reaproveitar revisões")
    a = ap.parse_args()

    data = load_json(a.posts)
    cfg = load_json(a.themes)
    old = {t["id"]: t for t in load_json(a.keep)["tags"]} if a.keep and Path(a.keep).exists() else {}
    vids = scan_videos(Path(a.videos)) if a.videos else []

    for p in data["videos"]:
        p["caption"] = p.get("title", "") + " " + p.get("description", "")
    texts = {p["id"]: split_caption(p["caption"]) for p in data["videos"]}
    matched = assign_videos(data["videos"], texts, vids) if vids else {}
    out = []
    for p in data["videos"]:
        text, tags = split_caption(p.get("description", ""))
        ttext, ttags = split_caption(p.get("title", ""))
        sent = first_sentence(text)
        ep = re.search(r"\bEP\.?\s*(\d+)", ttext + " " + text[:20], re.I)
        v = matched.get(p["id"])
        t = {
            "id": p["id"],
            "published_at": p["published_at"],
            "title": ttext,
            "title_format": title_format(ttext),
            "title_chars": len(ttext),
            "hook": sent,
            "hook_type": hook_type(sent, text) if sent else "?",
            "theme": theme_from(ttext + " " + text, ttags + tags, cfg.get("themes", {})),
            "region": region_from(ttext + " " + text, ttags + tags, cfg.get("regions", {})),
            "era": era_from(ttext + " " + text, ttags + tags),
            "series_ep": int(ep.group(1)) if ep else None,
            "caption_chars": len(text),
            "hashtags": len(ttags),
            "duration_s": p.get("duration_s") or (v and v["duration_s"]),
            "video_file": v and v["path"],
            "extra": {},
            "reviewed": False,
        }
        if p["id"] in old:
            keep = old[p["id"]]
            for k in ("theme", "region", "era", "hook_type", "title_format", "extra", "duration_s", "video_file", "reviewed"):
                if keep.get(k) not in (None, "?", {}):
                    t[k] = keep[k]
        out.append(t)

    dump_json({"note": "Revise theme/region/era/hook_type; '?' = não deduzido. Marque reviewed=true.",
               "tags": out}, a.out)
    unk = sum(1 for t in out for k in ("theme", "region", "era") if t[k] == "?")
    nodur = sum(1 for t in out if not t["duration_s"])
    print(f"{len(out)} posts → {a.out}  ({unk} campos '?', {nodur} sem duração)")
    for t in out:
        print(f"  {t['published_at'][:10]}  {t['title_format'][:16]:16}  {t['hook_type'][:16]:16}  {t['theme'][:24]:24}  "
              f"{t['era'][:12]:12}  {Path(t['video_file']).name if t['video_file'] else ''}")


if __name__ == "__main__":
    main()
