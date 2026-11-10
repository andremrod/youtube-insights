#!/usr/bin/env python3
"""Cruza métricas (videos.json) com características (tags.json) e gera analysis.json.

Por vídeo: views, tempo assistido, % média assistida, "continuaram assistindo" (Shorts: quem não
deslizou), inscritos por mil views, curtidas e compartilhamentos por view, impressões e CTR.
Estouro = views ≥ 2× mediana; flop = < 25% da mediana. Agrupa por tema, formato do título, gancho,
época, região, duração, dia da semana, vídeos no mesmo dia, série e formato (Short/vídeo);
correlação de Spearman com as views; achados com confiança pelo n; dicas automáticas.

Opcional:
  --account   account.json (fontes de tráfego, inscritos)
  --previous  analysis.json de uma rodada anterior (evolução)
  --cross     analysis.json da skill instagram-insights (o mesmo vídeo nas duas plataformas)

Uso:
  python3 analyze.py --videos runs/D/videos.json --tags runs/D/tags.json [--account ...] [--previous ...] \
      [--cross ~/Documents/instagram-insights/runs/D/analysis.json] --out runs/D/analysis.json
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import WEEKDAYS_PT, dump_json, fold, load_json, mean, median, safe_div, spearman  # noqa: E402

HIT_X, FLOP_X = 2.0, 0.25

DIMENSIONS = [
    ("theme", "Tema"),
    ("title_format", "Formato do título"),
    ("hook_type", "Gancho (1ª frase)"),
    ("era", "Época"),
    ("region", "Região"),
    ("duration_bucket", "Duração"),
    ("same_day", "Vídeos publicados no mesmo dia"),
    ("weekday", "Dia da semana"),
    ("series", "Série (EP.)"),
    ("hashtag_bucket", "Hashtags no título"),
    ("format", "Formato"),
]


def fx(x):
    return "—" if x is None else f"{x:.1f}×".replace(".", ",").replace(",0×", "×")


def fi(x):
    return "—" if x is None else f"{x:,.0f}".replace(",", ".")


def fp(x, d=1):
    return "—" if x is None else f"{x * 100:.{d}f}%".replace(".", ",")


def fr(x):
    return "—" if x is None else f"{x:+.2f}".replace(".", ",")


def conf(*ns):
    n = min(ns)
    return "forte" if n >= 5 else "média" if n >= 3 else "fraca"


def bucket_duration(d):
    if not d:
        return None
    return ("até 60 s" if d <= 60 else "61–90 s" if d <= 90 else "91–120 s" if d <= 120 else "121–180 s" if d <= 180
            else "3–8 min" if d <= 480 else "8–15 min" if d <= 900 else "mais de 15 min")


def enrich(videos, tags):
    by_day = {}
    for v in videos:
        by_day.setdefault((v.get("published_at") or "")[:10], []).append(v)
    rows = []
    for v in videos:
        t = tags.get(v["id"], {})
        pub = datetime.fromisoformat(v["published_at"]) if v.get("published_at") else None
        views = v.get("views")
        n_day = len(by_day.get((v.get("published_at") or "")[:10], []))
        r = {**{k: v.get(k) for k in ("id", "title", "url", "published_at", "format", "views", "watch_time_s", "avg_view_s",
                                      "avg_pct", "subs", "impressions", "ctr", "likes", "comments", "shares", "stayed",
                                      "duration_s", "description")},
             "hook": t.get("hook"), "theme": t.get("theme"), "title_format": t.get("title_format"),
             "hook_type": t.get("hook_type"), "era": t.get("era"), "region": t.get("region"),
             "series": "EP. de série" if t.get("series_ep") else "avulso",
             "hashtags": t.get("hashtags"),
             "hashtag_bucket": None if t.get("hashtags") is None else ("0" if t["hashtags"] == 0 else "1–2" if t["hashtags"] <= 2 else "3–4" if t["hashtags"] <= 4 else "5 ou mais"),
             "duration_bucket": bucket_duration(v.get("duration_s")),
             "weekday": WEEKDAYS_PT[pub.weekday()] if pub else None,
             "posts_same_day": n_day,
             "same_day": "1 no dia" if n_day == 1 else "2 no dia" if n_day == 2 else f"3+ no dia",
             "extra": t.get("extra") or {},
             "like_rate": safe_div(v.get("likes"), views),
             "share_rate": safe_div(v.get("shares"), views),
             "comment_rate": safe_div(v.get("comments"), views),
             "subs_per_1k": safe_div((v.get("subs") or 0) * 1000, views) if v.get("subs") is not None else None,
             "retention": v.get("avg_pct"),
             "days_live": None}
        for k, val in (t.get("extra") or {}).items():
            r[f"x_{k}"] = val
        rows.append(r)
    rows.sort(key=lambda r: r["published_at"] or "")
    for i, r in enumerate(rows, 1):
        r["order"] = i
    return rows


def group(rows, key, med):
    gs = {}
    for r in rows:
        if r.get(key) in (None, "?", ""):
            continue
        gs.setdefault(r[key], []).append(r)
    out = []
    for name, rs in gs.items():
        m = median([r["views"] for r in rs])
        out.append({"group": name, "n": len(rs), "median_views": m, "mean_views": round(mean([r["views"] for r in rs]) or 0, 1),
                    "total_views": sum(r["views"] or 0 for r in rs),
                    "hit_rate": sum(r["hit"] for r in rs) / len(rs), "flop_rate": sum(r["flop"] for r in rs) / len(rs),
                    "lift": round(m / med, 2) if m is not None and med else None,
                    "median_stayed": median([r["stayed"] for r in rs]),
                    "median_retention": median([r["retention"] for r in rs]),
                    "median_like_rate": median([r["like_rate"] for r in rs]),
                    "median_subs_per_1k": median([r["subs_per_1k"] for r in rs]),
                    "median_ctr": median([r["ctr"] for r in rs]),
                    "post_ids": [r["id"] for r in rs]})
    out.sort(key=lambda g: (-(g["median_views"] or 0), -g["n"]))
    return out


def cross_match(rows, other):
    """Casa cada vídeo com o post do Instagram pela data (±1 dia) e palavras em comum."""
    def toks(s):
        return {w for w in re.findall(r"[a-z0-9]{4,}", fold(s or "")) if w not in {"para", "como", "porque", "quando", "segunda", "guerra", "mundial"}}
    out = []
    used = set()
    ig = other.get("posts", [])
    for r in rows:
        if not r.get("published_at"):
            continue
        d0 = datetime.fromisoformat(r["published_at"][:10])
        mine = toks(r["title"]) | toks(r.get("description"))
        best, score = None, 0
        for p in ig:
            if p["id"] in used:
                continue
            dp = datetime.fromisoformat(p["published_at"][:10])
            if abs((dp - d0).days) > 1:
                continue
            s = len(mine & toks((p.get("hook") or "") + " " + (p.get("caption") or "")))
            if s > score:
                best, score = p, s
        if best and score >= 3:
            used.add(best["id"])
            out.append({"yt_id": r["id"], "title": r["title"], "date": r["published_at"][:10],
                        "yt_views": r["views"], "ig_views": best["views"], "ig_id": best["id"],
                        "yt_hit": r["hit"], "ig_hit": best.get("hit"), "ig_flop": best.get("flop"),
                        "yt_stayed": r["stayed"], "ig_retention": best.get("retention")})
    return out


def findings(rows, dims, med, s, account, cross):
    F, T = [], []
    hits = [r for r in rows if r["hit"]]
    flops = [r for r in rows if r["flop"]]

    if account and account.get("traffic_sources"):
        ts = account["traffic_sources"]
        tot = sum(ts.values()) or 1
        top = sorted(ts.items(), key=lambda kv: -kv[1])
        F.append({"id": "traffic", "title": f"{fp(top[0][1] / tot, 0)} das views vêm de “{top[0][0]}”",
                  "text": "Fontes: " + "; ".join(f"{k} {fp(v / tot)}" for k, v in top[:4]) + ". "
                          + ("Quase tudo depende de o feed de Shorts escolher mostrar o vídeo: a decisão sai de quem continua assistindo em vez de deslizar."
                             if "short" in fold(top[0][0]) else ""),
                  "confidence": "forte", "evidence": []})
        search = sum(v for k, v in ts.items() if "pesquisa" in fold(k) or "search" in fold(k))
        if search / tot >= 0.03:
            T.append({"priority": 2, "title": "Título que as pessoas digitariam na busca",
                      "text": f"{fp(search / tot)} das views vieram da pesquisa do YouTube. Títulos em forma de pergunta "
                              "com o nome do evento (“Por que…”, “Como…”) são o que alguém digita. Vale manter o nome do evento no começo do título.",
                      "based_on": "traffic"})

    st = [r for r in rows if r["stayed"] is not None]
    if len(st) >= 5:
        rho = spearman([r["stayed"] for r in st], [r["views"] for r in st])
        hs = median([r["stayed"] for r in st if r["hit"]])
        ns = median([r["stayed"] for r in st if not r["hit"]])
        F.append({"id": "stayed", "title": f"Em média {fp(median([r['stayed'] for r in st]), 0)} continuam assistindo em vez de deslizar",
                  "text": (f"Nos estouros, {fp(hs, 0)}; nos demais, {fp(ns, 0)}. " if hs is not None and ns is not None else "")
                          + f"Correlação com as views: {fr(rho)}. "
                          + "Os piores: " + "; ".join(f"“{r['title'][:40]}…” ({fp(r['stayed'], 0)})" for r in sorted(st, key=lambda r: r["stayed"])[:3]) + ".",
                  "confidence": conf(len(st)), "evidence": [r["id"] for r in sorted(st, key=lambda r: r["stayed"])[:3]]})
        T.append({"priority": 1, "title": "O primeiro segundo decide",
                  "text": "No feed de Shorts, o vídeo só é empurrado se quem vê não deslizar. Comece com a imagem mais forte e a "
                          "pergunta já na tela; evite abrir com título estático ou fundo escuro. Compare o ‘continuaram assistindo’ na próxima rodada.",
                  "based_on": "stayed"})

    rt = [r for r in rows if r["retention"] is not None]
    if len(rt) >= 5:
        rho_d = spearman([r["duration_s"] for r in rt], [r["retention"] for r in rt])
        F.append({"id": "retention", "title": f"Quem fica assiste {fp(median([r['retention'] for r in rt]), 0)} do vídeo (mediana)",
                  "text": f"Duração média assistida: {fi(median([r['avg_view_s'] for r in rt]))} s. "
                          f"Correlação duração × % assistida: {fr(rho_d)}. "
                          + "Abaixo de 50%: " + ("; ".join(f"“{r['title'][:38]}…” ({fp(r['retention'], 0)}, {fi(r['duration_s'])} s)"
                                                       for r in rt if r["retention"] < 0.5) or "nenhum") + ".",
                  "confidence": conf(len(rt)), "evidence": [r["id"] for r in rt if r["retention"] < 0.5]})

    for key, label in DIMENSIONS:
        gs = [g for g in dims.get(key, []) if g["n"] >= 2]
        if len(gs) < 2:
            continue
        b, w = gs[0], gs[-1]
        if not b["median_views"] or not w["median_views"] or b["median_views"] < 1.3 * w["median_views"]:
            continue
        F.append({"id": f"dim_{key}", "title": f"{label}: “{b['group']}” rende mais",
                  "text": f"Mediana de {fi(b['median_views'])} views em {b['n']} vídeos ({fx(b['lift'])} a mediana do canal; "
                          f"{fp(b['hit_rate'], 0)} viraram estouro), contra {fi(w['median_views'])} em “{w['group']}” ({w['n']} vídeos)."
                          + (" Poucos vídeos por grupo: trate como pista." if min(b["n"], w["n"]) < 3 else ""),
                  "confidence": conf(b["n"], w["n"]), "evidence": b["post_ids"]})

    if hits:
        common = []
        for key, label in DIMENSIONS:
            vals = [h.get(key) for h in hits if h.get(key) not in (None, "?")]
            if not vals:
                continue
            top = max(set(vals), key=vals.count)
            base = sum(1 for r in rows if r.get(key) == top) / len(rows)
            if vals.count(top) / len(hits) >= 0.75 and vals.count(top) / len(hits) > base + 0.15:
                common.append(f"{label.lower()} = {top} ({vals.count(top)}/{len(hits)} estouros; {fp(base, 0)} dos vídeos)")
        F.append({"id": "hits", "title": f"{len(hits)} estouros (≥2× a mediana) somam {fp(sum(h['views'] for h in hits) / max(1, s['total_views']), 0)} das views",
                  "text": ("Em comum: " + "; ".join(common) + ".") if common else "Os estouros não dividem um mesmo padrão claro.",
                  "confidence": conf(len(hits)), "evidence": [h["id"] for h in hits]})

    if s["total_subs"]:
        best = sorted([r for r in rows if r["subs"]], key=lambda r: -(r["subs"] or 0))[:3]
        F.append({"id": "subs", "title": f"{fi(s['total_subs'])} inscritos ganhos",
                  "text": "Mais inscritos: " + "; ".join(f"“{r['title'][:45]}…” ({fi(r['subs'])}, {r['subs_per_1k']:.1f} por mil views)".replace(".", ",", 1) for r in best) + ".",
                  "confidence": conf(len([r for r in rows if r["subs"]])), "evidence": [r["id"] for r in best]})

    days = {}
    for r in rows:
        days.setdefault((r["published_at"] or "")[:10], []).append(r)
    multi = {d: rs for d, rs in days.items() if len(rs) >= 3}
    few = [r for d, rs in days.items() if len(rs) < 3 for r in rs]
    multi_views = [r["views"] for rs in multi.values() for r in rs]
    if multi and few and (median(multi_views) or 0) < (median([r["views"] for r in few]) or 0):
        worst = [min(rs, key=lambda r: r["views"]) for rs in multi.values()]
        F.append({"id": "same_day", "title": f"{len(multi)} dia(s) com 3 ou mais vídeos",
                  "text": "Nesses dias o vídeo mais fraco teve mediana de "
                          f"{fi(median([w['views'] for w in worst]))} views, contra {fi(med)} do canal: "
                          + "; ".join(f"{d[8:]}/{d[5:7]}: " + ", ".join(fi(r['views']) for r in sorted(rs, key=lambda r: -r['views'])) for d, rs in sorted(multi.items())) + ".",
                  "confidence": conf(len(worst)), "evidence": [w["id"] for w in worst]})
        T.append({"priority": 2, "title": "Um ou dois Shorts por dia",
                  "text": "Em dias com 3+ uploads, os últimos da fila competem entre si pelo mesmo público inicial. Espalhe os vídeos prontos pela semana.",
                  "based_on": "same_day"})

    if cross:
        rho = spearman([c["yt_views"] for c in cross], [c["ig_views"] for c in cross])
        div = sorted(cross, key=lambda c: -(c["yt_views"] / max(1, c["ig_views"])))[:3]
        F.append({"id": "cross", "title": f"O mesmo vídeo vai bem numa plataforma e mal na outra",
                  "text": f"{len(cross)} vídeos estão nas duas. Correlação entre as views do YouTube e do Instagram: {fr(rho)}. "
                          "Maiores diferenças: " + "; ".join(f"“{c['title'][:36]}…” ({fi(c['yt_views'])} no YouTube × {fi(c['ig_views'])} no Instagram)" for c in div) + ".",
                  "confidence": conf(len(cross)), "evidence": [c["yt_id"] for c in div]})
        T.append({"priority": 1, "title": "Um vídeo fraco numa plataforma não é um tema ruim",
                  "text": "Quando o mesmo vídeo vai bem numa e mal na outra, a causa costuma ser a distribuição (dia, horário, posts colados) e não o assunto. "
                          "Republique na plataforma em que falhou antes de descartar o tema.",
                  "based_on": "cross"})

    corr = {}
    for k in ("stayed", "retention", "avg_view_s", "duration_s", "ctr", "impressions", "like_rate", "posts_same_day", "hashtags", "order"):
        rho = spearman([r.get(k) for r in rows], [r["views"] for r in rows])
        if rho is not None:
            corr[k] = rho
    s["correlations_with_views"] = corr

    if flops:
        F.append({"id": "flops", "title": f"{len(flops)} vídeos quase não foram distribuídos",
                  "text": "; ".join(f"“{r['title'][:45]}…” ({fi(r['views'])} views, continuaram assistindo {fp(r['stayed'], 0)})" for r in flops) + ".",
                  "confidence": conf(len(flops)), "evidence": [r["id"] for r in flops]})
    T.sort(key=lambda t: t["priority"])
    return F, T


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--videos", required=True)
    ap.add_argument("--tags", required=True)
    ap.add_argument("--account")
    ap.add_argument("--previous")
    ap.add_argument("--cross")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    vd = load_json(a.videos)
    videos = [v for v in vd["videos"] if v.get("views") is not None]
    tags = {t["id"]: t for t in load_json(a.tags)["tags"]}
    rows = enrich(videos, tags)
    med = median([r["views"] for r in rows])
    ref = datetime.fromisoformat(vd["collected_at"]) if vd.get("collected_at") else datetime.now()
    for r in rows:
        r["hit"] = bool(med and r["views"] >= HIT_X * med)
        r["flop"] = bool(med and r["views"] < FLOP_X * med)
        r["lift"] = round(r["views"] / med, 2) if med else None
        if r["published_at"]:
            r["days_live"] = max(0, (ref - datetime.fromisoformat(r["published_at"])).days)
    s = {"videos": len(rows), "first": rows[0]["published_at"] if rows else None, "last": rows[-1]["published_at"] if rows else None,
         "total_views": sum(r["views"] or 0 for r in rows), "median_views": med, "mean_views": round(mean([r["views"] for r in rows]) or 0, 1),
         "total_watch_h": round(sum(r["watch_time_s"] or 0 for r in rows) / 3600, 1),
         "median_stayed": median([r["stayed"] for r in rows]), "median_retention": median([r["retention"] for r in rows]),
         "median_avg_view_s": median([r["avg_view_s"] for r in rows]),
         "total_subs": sum(r["subs"] or 0 for r in rows), "total_likes": sum(r["likes"] or 0 for r in rows),
         "total_shares": sum(r["shares"] or 0 for r in rows), "total_comments": sum(r["comments"] or 0 for r in rows),
         "total_impressions": sum(r["impressions"] or 0 for r in rows), "median_ctr": median([r["ctr"] for r in rows]),
         "median_like_rate": median([r["like_rate"] for r in rows]),
         "hits": sum(r["hit"] for r in rows), "flops": sum(r["flop"] for r in rows),
         "hit_rule": f"views ≥ {HIT_X:.0f}× mediana", "flop_rule": f"views < {int(FLOP_X * 100)}% da mediana",
         "shorts": sum(1 for r in rows if r["format"] == "short")}
    distributed = [r for r in rows if not r["flop"]] if len(rows) - s["flops"] >= 5 else rows
    dims = {k: group(rows if k == "same_day" else distributed, k, med) for k, _ in DIMENSIONS}
    extra = sorted({k for r in rows for k in r if k.startswith("x_")})
    for k in extra:
        dims[k] = group(distributed, k, med)
    s["dimension_basis"] = (f"{len(distributed)} vídeos distribuídos (sem os {s['flops']} flops)" if len(distributed) < len(rows)
                            else f"todos os {len(rows)} vídeos")
    account = load_json(a.account) if a.account and Path(a.account).exists() else None
    cross = cross_match(rows, load_json(a.cross)) if a.cross and Path(a.cross).exists() else []
    F, T = findings(rows, dims, med, s, account, cross)
    out = {"platform": "youtube", "channel": vd.get("channel"), "collected_at": vd.get("collected_at"), "summary": s,
           "dimension_labels": dict(DIMENSIONS) | {k: k[2:] for k in extra}, "dimensions": dims, "posts": rows,
           "findings": F, "auto_tips": T, "cross": cross}
    if account:
        out["account_stats"] = account
    if a.previous and Path(a.previous).exists():
        prev = load_json(a.previous)
        pv = {p["id"]: p for p in prev["posts"]}
        out["previous"] = {"collected_at": prev.get("collected_at"), "summary": prev["summary"],
                           "post_growth": {r["id"]: (r["views"] or 0) - (pv[r["id"]]["views"] or 0) for r in rows if r["id"] in pv},
                           "new_posts": [r["id"] for r in rows if r["id"] not in pv]}
    dump_json(out, a.out)
    print(f"{s['videos']} vídeos | views: total {s['total_views']:.0f}, mediana {med:.0f} | estouros {s['hits']} | flops {s['flops']}"
          + (f" | {len(cross)} casados com o Instagram" if cross else "") + f" → {a.out}")
    for f in F:
        print(f" • [{f['confidence']}] {f['title']}\n     {f['text']}")


if __name__ == "__main__":
    main()
