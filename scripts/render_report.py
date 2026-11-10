#!/usr/bin/env python3
"""analysis.json (+ notes.json escrito pelo Claude) → report.html autocontido, com gráficos SVG,
tooltips, tema claro/escuro, tabela de todos os vídeos e comparação com o Instagram.

notes.json (opcional; tudo em PT, só com fatos do analysis.json — nada inventado):
{
  "headline": "frase única com o principal aprendizado",
  "summary": "2–4 frases",
  "tips": [{"title": "...", "text": "...", "evidence": "o número que sustenta"}],
  "next_videos": [{"title": "tema/ideia", "why": "qual dado sustenta"}],
  "experiments": [{"test": "o que testar", "how": "como", "metric": "o que olhar na próxima rodada"}],
  "caveats": ["limites dos dados"]
}

Uso: python3 render_report.py --analysis runs/D/analysis.json [--notes runs/D/notes.json] --out runs/D/report.html
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_json  # noqa: E402

E = html.escape
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def n0(x):
    return "—" if x is None else f"{x:,.0f}".replace(",", ".")


def pct(x, d=1):
    return "—" if x is None else f"{x * 100:.{d}f}%".replace(".", ",")


def secs(x):
    if x is None:
        return "—"
    x = int(round(x))
    if x >= 3600:
        return f"{x // 3600} h {x % 3600 // 60} min"
    return f"{x // 60} min {x % 60} s" if x >= 60 else f"{x} s"


def short_date(iso):
    d = datetime.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]}"


def nice_max(v):
    if v <= 0:
        return 1
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if m * e >= v:
            return m * e
    return 10 * e


def tip_attr(d: dict) -> str:
    return f' tabindex="0" data-tip="{E(json.dumps(d, ensure_ascii=False))}"'


def post_tip(p):
    return {"t": (p.get("title") or "")[:110], "d": short_date(p["published_at"]),
            "rows": [["Views", n0(p["views"])], ["Continuaram assistindo", pct(p["stayed"], 0)],
                     ["% assistida", pct(p["retention"], 0)],
                     ["Duração média", secs(p["avg_view_s"]) + (f" de {secs(p['duration_s'])}" if p.get("duration_s") else "")],
                     ["Inscritos", n0(p["subs"])], ["Curtidas", n0(p["likes"])], ["Compartilhamentos", n0(p["shares"])],
                     ["CTR da miniatura", pct(p["ctr"])], ["Tema", p.get("theme") or "—"]]}


def state(p):
    return "hit" if p["hit"] else "flop" if p["flop"] else "base"


# ───────────────────────── gráficos ─────────────────────────

def chart_timeline(posts, med):
    W, H, L, R, T, B = 760, 280, 48, 12, 22, 44
    vmax = nice_max(max(p["views"] or 0 for p in posts))
    n = len(posts)
    step = (W - L - R) / n
    bw = max(4, min(26, step - 4))
    y = lambda v: T + (H - T - B) * (1 - v / vmax)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Views de cada post em ordem de publicação">']
    for k in range(5):
        v = vmax * k / 4
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                   f'<text class="tick" x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{n0(v)}</text>')
    for i, p in enumerate(posts):
        x = L + i * step + (step - bw) / 2
        v = p["views"] or 0
        h = max(1.5, (H - T - B) - (y(v) - T))
        r = min(4, bw / 2, h)
        top = H - B - h
        path = (f"M{x:.1f},{H - B} V{top + r:.1f} Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} H{x + bw - r:.1f} "
                f"Q{x + bw:.1f},{top:.1f} {x + bw:.1f},{top + r:.1f} V{H - B} Z")
        out.append(f'<g class="mark"{tip_attr(post_tip(p))}><rect class="hit-area" x="{L + i * step:.1f}" y="{T}" '
                   f'width="{step:.1f}" height="{H - T - B}"/><path class="bar {state(p)}" d="{path}"/></g>')
        if p["hit"]:
            out.append(f'<text class="vlabel" x="{x + bw / 2:.1f}" y="{top - 6:.1f}" text-anchor="middle">{n0(v)}</text>')
        if i % max(1, n // 10) == 0 or i == n - 1:
            out.append(f'<text class="tick" x="{x + bw / 2:.1f}" y="{H - B + 16}" text-anchor="middle">{short_date(p["published_at"])}</text>')
    if med:
        out.append(f'<line class="ref" x1="{L}" x2="{W - R}" y1="{y(med):.1f}" y2="{y(med):.1f}"/>'
                   f'<text class="reflabel" x="{W - R}" y="{y(med) - 6:.1f}" text-anchor="end">mediana {n0(med)}</text>')
    out.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{H - B}" y2="{H - B}"/></svg>')
    return "".join(out)


def chart_hbars(groups, med, label):
    gs = [g for g in groups if g["median_views"] is not None][:8]
    if not gs:
        return ""
    rowh, L, R, T = 34, 190, 70, 8
    W = 560
    H = T + rowh * len(gs) + 18
    vmax = nice_max(max(max(g["median_views"] for g in gs), med or 0))
    sx = lambda v: L + (W - L - R) * v / vmax
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Mediana de views por {E(label)}">']
    for k in range(5):
        v = vmax * k / 4
        out.append(f'<line class="grid" x1="{sx(v):.1f}" x2="{sx(v):.1f}" y1="{T}" y2="{H - 18}"/>')
    for i, g in enumerate(gs):
        yb = T + i * rowh + 7
        bh = rowh - 14
        w = max(2, sx(g["median_views"]) - L)
        r = min(4, bh / 2, w)
        path = (f"M{L},{yb} H{L + w - r:.1f} Q{L + w:.1f},{yb} {L + w:.1f},{yb + r} V{yb + bh - r} "
                f"Q{L + w:.1f},{yb + bh} {L + w - r:.1f},{yb + bh} H{L} Z")
        tip = {"t": str(g["group"]), "d": f"{g['n']} vídeos",
               "rows": [["Mediana de views", n0(g["median_views"])], ["Média de views", n0(g["mean_views"])],
                        ["× mediana da conta", (f"{g['lift']:.1f}×".replace(".", ",") if g["lift"] else "—")],
                        ["Viraram estouro", pct(g["hit_rate"], 0)], ["Continuaram assistindo", pct(g["median_stayed"], 0)],
                        ["% assistida (mediana)", pct(g["median_retention"], 0)],
                        ["Inscritos por mil", (f"{g['median_subs_per_1k']:.1f}".replace(".", ",") if g["median_subs_per_1k"] is not None else "—")]]}
        name = str(g["group"])
        name = name if len(name) <= 28 else name[:27] + "…"
        out.append(f'<g class="mark"{tip_attr(tip)}><rect class="hit-area" x="0" y="{T + i * rowh}" width="{W}" height="{rowh}"/>'
                   f'<text class="cat" x="{L - 10}" y="{yb + bh / 2 + 4:.1f}" text-anchor="end">{E(name)}</text>'
                   f'<path class="bar base" d="{path}"/>'
                   f'<text class="val" x="{L + w + 6:.1f}" y="{yb + bh / 2 + 4:.1f}">{n0(g["median_views"])}'
                   f'<tspan class="muted"> · {g["n"]}</tspan></text></g>')
    if med:
        out.append(f'<line class="ref" x1="{sx(med):.1f}" x2="{sx(med):.1f}" y1="{T - 4}" y2="{H - 18}"/>'
                   f'<text class="reflabel" x="{sx(med) + 4:.1f}" y="{H - 4}">mediana do canal {n0(med)}</text>')
    out.append("</svg>")
    return "".join(out)


def chart_scatter(posts, xkey, xlabel, xfmt, logy=True):
    pts = [p for p in posts if p.get(xkey) is not None and p["views"]]
    if len(pts) < 4:
        return ""
    W, H, L, R, T, B = 560, 300, 54, 16, 14, 42
    xs = [p[xkey] for p in pts]
    x0, x1 = min(xs), max(xs)
    pad = (x1 - x0) * 0.08 or 1
    x0, x1 = x0 - pad, x1 + pad
    vmin, vmax = min(p["views"] for p in pts), max(p["views"] for p in pts)
    ylo = 10 ** math.floor(math.log10(max(1, vmin)))
    yhi = 10 ** math.ceil(math.log10(vmax))
    sx = lambda v: L + (W - L - R) * (v - x0) / (x1 - x0)
    sy = lambda v: T + (H - T - B) * (1 - (math.log10(max(v, ylo)) - math.log10(ylo)) / (math.log10(yhi) - math.log10(ylo)))
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Views por {E(xlabel)}">']
    e = ylo
    while e <= yhi:
        out.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{sy(e):.1f}" y2="{sy(e):.1f}"/>'
                   f'<text class="tick" x="{L - 6}" y="{sy(e) + 4:.1f}" text-anchor="end">{n0(e)}</text>')
        e *= 10
    for k in range(5):
        v = x0 + (x1 - x0) * k / 4
        out.append(f'<text class="tick" x="{sx(v):.1f}" y="{H - B + 16}" text-anchor="middle">{E(xfmt(v))}</text>')
    out.append(f'<text class="axlabel" x="{(L + W - R) / 2}" y="{H - 6}" text-anchor="middle">{E(xlabel)}</text>')
    out.append(f'<text class="axlabel" x="12" y="{T + 4}" transform="rotate(-90 12 {T + 4})" text-anchor="end">views (escala log)</text>')
    for p in sorted(pts, key=lambda p: p["hit"]):
        out.append(f'<g class="mark"{tip_attr(post_tip(p))}><circle class="hit-area" cx="{sx(p[xkey]):.1f}" cy="{sy(p["views"]):.1f}" r="12"/>'
                   f'<circle class="dot {state(p)}" cx="{sx(p[xkey]):.1f}" cy="{sy(p["views"]):.1f}" r="5.5"/></g>')
    out.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{H - B}" y2="{H - B}"/></svg>')
    return "".join(out)


def cross_section(cross):
    if not cross:
        return ""
    vmax = max(max(c["yt_views"] or 0, c["ig_views"] or 0) for c in cross) or 1
    rows = []
    for c in sorted(cross, key=lambda c: c["date"]):
        ratio = (c["yt_views"] or 0) / max(1, c["ig_views"] or 0)
        tag = "melhor no YouTube" if ratio >= 3 else "melhor no Instagram" if ratio <= 1 / 3 else "parecido"
        rows.append(f'<tr><td>{E(short_date(c["date"]))}</td><td>{E(re.sub(r"[ ]*#[^ ]+", "", c["title"])[:60])}</td>'
                    f'<td class="num">{n0(c["yt_views"])}</td><td><span class="pair"><i class="yt" style="--w:{100 * (c["yt_views"] or 0) / vmax:.1f}%"></i></span></td>'
                    f'<td class="num">{n0(c["ig_views"])}</td><td><span class="pair"><i class="ig" style="--w:{100 * (c["ig_views"] or 0) / vmax:.1f}%"></i></span></td>'
                    f'<td class="muted">{tag}</td></tr>')
    return ('<section class="card"><h2>O mesmo vídeo no YouTube e no Instagram</h2>'
            '<p class="sub">Casados pela data e pelas palavras do título. Barras na mesma escala.</p>'
            '<div class="tablewrap"><table class="plain"><thead><tr><th>Data</th><th>Vídeo</th><th class="num">YouTube</th><th></th>'
            '<th class="num">Instagram</th><th></th><th>Onde foi melhor</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
            '<div class="legend"><span><i class="sw base"></i>YouTube</span><span><i class="sw ig"></i>Instagram</span></div></section>')


LEGEND = ('<div class="legend"><span><i class="sw hit"></i>Estouro (≥2× a mediana)</span>'
          '<span><i class="sw base"></i>Normal</span><span><i class="sw flop"></i>Não distribuído (&lt;25% da mediana)</span></div>')


# ───────────────────────── página ─────────────────────────

def build(an: dict, notes: dict) -> str:
    s = an["summary"]
    posts = an["posts"]
    med = s["median_views"]
    acct = an.get("channel") or "YouTube"
    period = f"{short_date(s['first'])} a {short_date(s['last'])}" if s.get("first") else ""
    labels = an["dimension_labels"]

    kpis = [
        ("Views", n0(s["total_views"]), f"{s['videos']} vídeos · mediana {n0(med)} por vídeo"),
        ("Tempo assistido", f"{n0(s['total_watch_h'])} h", f"{secs(s['median_avg_view_s'])} por view (mediana)"),
        ("Continuaram assistindo", pct(s["median_stayed"], 0), "Shorts: não deslizaram (mediana)"),
        ("% assistida", pct(s["median_retention"], 0), "porcentagem média do vídeo (mediana)"),
        ("Estouros", f"{s['hits']}", s["hit_rule"]),
        ("Inscritos ganhos", n0(s["total_subs"]), f"{n0(s['total_likes'])} curtidas · {n0(s['total_shares'])} compart."),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="kpi-l">{E(a)}</div><div class="kpi-v">{E(b)}</div>'
                       f'<div class="kpi-s">{E(c)}</div></div>' for a, b, c in kpis)

    conf_cls = {"forte": "c-high", "média": "c-mid", "fraca": "c-low"}
    findings = "".join(
        f'<article class="finding"><div class="f-head"><h3>{E(f["title"])}</h3>'
        f'<span class="badge {conf_cls.get(f["confidence"], "c-low")}">confiança {E(f["confidence"])}</span></div>'
        f'<p>{E(f["text"])}</p></article>' for f in an["findings"])

    dim_cards = []
    for key in ("theme", "title_format", "hook_type", "era", "duration_bucket", "same_day", "weekday", "series", "region",
                "hashtag_bucket", "format") + tuple(k for k in an["dimensions"] if k.startswith("x_")):
        gs = an["dimensions"].get(key) or []
        if len(gs) < 2:
            continue
        dim_cards.append(f'<section class="card"><h3>{E(labels.get(key, key))}</h3>'
                         f'<p class="sub">Mediana de views por grupo · número de vídeos depois do ponto</p>'
                         f'{chart_hbars(gs, med, labels.get(key, key))}</section>')

    tips = notes.get("tips") or []
    auto = an.get("auto_tips") or []
    tip_html = "".join(f'<li><strong>{E(t["title"])}</strong><span>{E(t["text"])}</span>'
                       + (f'<em>Base: {E(t["evidence"])}</em>' if t.get("evidence") else "") + "</li>" for t in tips)
    auto_html = "".join(f'<li><strong>{E(t["title"])}</strong><span>{E(t["text"])}</span></li>' for t in auto)
    nxt = "".join(f'<li><strong>{E(v["title"])}</strong><span>{E(v.get("why", ""))}</span></li>' for v in notes.get("next_videos") or [])
    exp = "".join(f'<tr><td>{E(x["test"])}</td><td>{E(x.get("how", ""))}</td><td>{E(x.get("metric", ""))}</td></tr>'
                  for x in notes.get("experiments") or [])
    cav = "".join(f"<li>{E(c)}</li>" for c in notes.get("caveats") or [])

    corr = s.get("correlations_with_views") or {}
    corr_names = {"stayed": "Continuaram assistindo (não deslizaram)", "retention": "% assistida", "avg_view_s": "Duração média da visualização",
                  "duration_s": "Duração do vídeo", "ctr": "CTR da miniatura", "impressions": "Impressões de miniatura",
                  "like_rate": "Curtidas por view", "posts_same_day": "Vídeos no mesmo dia", "hashtags": "Hashtags no título",
                  "order": "Ordem de publicação (canal mais velho)"}
    corr_rows = "".join(
        f'<tr><td>{E(corr_names.get(k, k))}</td><td class="num">{v:+.2f}'.replace(".", ",") +
        f'</td><td><span class="corrbar"><i style="--w:{abs(v) * 100:.0f}%" class="{"pos" if v >= 0 else "neg"}"></i></span></td>'
        f'<td class="muted">{"forte" if abs(v) >= .5 else "moderada" if abs(v) >= .3 else "fraca"}</td></tr>'
        for k, v in sorted(corr.items(), key=lambda kv: -abs(kv[1])))

    cols = [("Data", "published_at"), ("Título", "title"), ("Tema", "theme"), ("Views", "views"), ("Ficaram", "stayed"),
            ("% assist.", "retention"), ("Méd.", "avg_view_s"), ("Dur.", "duration_s"), ("Insc.", "subs"),
            ("Curt.", "likes"), ("Compart.", "shares"), ("CTR", "ctr"), ("No dia", "posts_same_day")]
    fmt = {"published_at": short_date, "views": n0, "stayed": lambda v: pct(v, 0), "retention": lambda v: pct(v, 0),
           "avg_view_s": lambda v: "—" if v is None else f"{v:.0f} s", "duration_s": lambda v: "—" if v is None else f"{v:.0f} s",
           "subs": n0, "likes": n0, "shares": n0, "ctr": pct, "posts_same_day": n0,
           "title": lambda v: re.sub(r"\s*#\w+", "", v or "")[:70], "theme": lambda v: v or "—"}
    head = "".join(f'<th data-k="{k}" class="{"num" if k not in ("title", "theme") else ""}"><button>{E(c)}</button></th>' for c, k in cols)
    body = "".join(
        f'<tr class="{state(p)}">' + "".join(
            f'<td class="{"num" if k not in ("title", "theme") else ""}" data-v="{E(str(p.get(k) if p.get(k) is not None else ""))}">'
            f'{E(fmt[k](p.get(k)))}</td>' for _, k in cols) + "</tr>"
        for p in sorted(posts, key=lambda p: p["published_at"], reverse=True))

    prev = an.get("previous")
    prev_html = ""
    if prev:
        ps = prev["summary"]
        grow = prev.get("post_growth") or {}
        prev_html = (f'<section class="card"><h2>Desde a rodada de {E(prev["collected_at"][:10])}</h2><p>'
                     f'Views totais {n0(ps["total_views"])} → {n0(s["total_views"])}; mediana por post {n0(ps["median_views"])} → {n0(med)}; '
                     f'{len(prev.get("new_posts", []))} vídeos novos; os antigos ganharam {n0(sum(grow.values()))} views.</p></section>')

    acct_stats = an.get("account_stats") or {}
    acct_note = ""
    if acct_stats.get("last_28d"):
        l = acct_stats["last_28d"]
        acct_note = ""
    if acct_stats.get("traffic_sources"):
        ts = acct_stats["traffic_sources"]
        tot = sum(ts.values()) or 1
        acct_note = ('<p class="sub">De onde vieram as views: ' + E("; ".join(f"{k} {pct(v / tot)}" for k, v in sorted(ts.items(), key=lambda kv: -kv[1])[:4]))
                     + (f'. Inscritos no canal: {n0(acct_stats.get("subscribers"))}.' if acct_stats.get("subscribers") else ".") + '</p>')

    return TEMPLATE.format(
        title=E(f"YouTube {acct}"), acct=E(acct), period=E(period), collected=E((an.get("collected_at") or "")[:10]),
        headline=E(notes.get("headline") or "O que funcionou nos seus vídeos"),
        summary=E(notes.get("summary") or ""), kpis=kpi_html, acct_note=acct_note, prev=prev_html,
        timeline=chart_timeline(posts, med), legend=LEGEND, findings=findings,
        dims="".join(dim_cards),
        sc1=chart_scatter(posts, "stayed", "continuaram assistindo (%)", lambda v: f"{v * 100:.0f}%"),
        sc2=chart_scatter(posts, "retention", "porcentagem assistida (%)", lambda v: f"{v * 100:.0f}%"),
        cross=cross_section(an.get("cross") or []),
        corr=corr_rows, tips=tip_html or auto_html,
        auto=(f'<details class="auto"><summary>Regras automáticas da análise ({len(auto)})</summary><ul class="tips">{auto_html}</ul></details>'
              if tip_html and auto_html else ""),
        nxt=(f'<section class="card"><h2>Próximos vídeos</h2><ul class="tips">{nxt}</ul></section>' if nxt else ""),
        exp=(f'<section class="card"><h2>Testes para as próximas semanas</h2><div class="tablewrap"><table class="plain">'
             f'<thead><tr><th>Teste</th><th>Como</th><th>O que medir</th></tr></thead><tbody>{exp}</tbody></table></div></section>' if exp else ""),
        cav=cav, basis=E(s.get("dimension_basis", "")), head=head, body=body, hit_rule=E(s["hit_rule"]), flop_rule=E(s["flop_rule"]),
    )


TEMPLATE = """<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap">
<style>
/* Layout: coluna única de leitura; números primeiro, depois achados, dicas e gráficos por dimensão em grade de 2 */
:root{{--display:"Space Grotesk",-apple-system,"Segoe UI",sans-serif;--body:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color-scheme:light;--bg:#f6f5f2;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#7a7974;--line:#e4e2dc;--grid:#ecebe6;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--flop:#b9b7b0;--accent:#2a78d6;--hi:#1a7f4b;--mid:#a86a00;--lo:#7a7974;--neg:#c23b3a}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8f8e86;
--line:#2c2c2a;--grid:#262624;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--flop:#55544f;--accent:#3987e5;--hi:#4cb782;--mid:#d9a441;--lo:#8f8e86;--neg:#e66767}}}}
:root[data-theme="dark"]{{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8f8e86;
--line:#2c2c2a;--grid:#262624;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--flop:#55544f;--accent:#3987e5;--hi:#4cb782;--mid:#d9a441;--lo:#8f8e86;--neg:#e66767}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--body)}}
main{{max-width:1120px;margin:0 auto;padding-block:32px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}}
h1,h2,h3,.kpi-v{{font-family:var(--display);text-wrap:balance}}
header h1{{font-size:clamp(26px,4vw,38px);line-height:1.15;margin:6px 0 10px;letter-spacing:-.01em;max-width:24ch}}
.lead{{max-width:68ch}} .findings>*,.grid2>*{{min-width:0}}
.eyebrow{{color:var(--ink2);font-size:13px;letter-spacing:.04em;text-transform:uppercase}}
.lead{{color:var(--ink2);max-width:760px;font-size:16px;margin:0}}
h2{{font-size:20px;margin:0 0 6px}} h3{{font-size:16px;margin:0 0 4px}}
.sub{{color:var(--muted);font-size:13px;margin:0 0 10px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:24px 0 8px}}
.kpi{{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px}}
.kpi-l{{color:var(--ink2);font-size:13px}} .kpi-v{{font-size:28px;font-weight:650;letter-spacing:-.02em;margin:2px 0}}
.kpi-s{{color:var(--muted);font-size:12px}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:20px;margin:16px 0}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:16px}}
.grid2 .card{{margin:0}}
.findings{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:12px}}
.finding{{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px}}
.finding p{{margin:6px 0 0;color:var(--ink2);font-size:14px}}
.f-head{{display:flex;gap:10px;justify-content:space-between;align-items:flex-start}}
.badge{{font-size:11px;white-space:nowrap;border-radius:999px;padding:2px 8px;border:1px solid currentColor}}
.c-high{{color:var(--hi)}} .c-mid{{color:var(--mid)}} .c-low{{color:var(--lo)}}
svg{{width:100%;height:auto;display:block;overflow:visible}}
.grid{{stroke:var(--grid);stroke-width:1}} .axis{{stroke:var(--line);stroke-width:1}}
.tick,.reflabel,.axlabel{{fill:var(--muted);font-size:11px}} .cat{{fill:var(--ink2);font-size:12px}}
.val,.vlabel{{fill:var(--ink);font-size:12px;font-weight:600}} .muted{{fill:var(--muted);color:var(--muted);font-weight:400}}
.ref{{stroke:var(--ink2);stroke-width:1;stroke-dasharray:4 4}}
.bar.base,.dot.base{{fill:var(--s1)}} .bar.hit,.dot.hit{{fill:var(--s2)}} .bar.flop,.dot.flop{{fill:var(--flop)}}
.dot{{stroke:var(--surface);stroke-width:2}}
.hit-area{{fill:transparent}} .mark{{cursor:default;outline:none}}
.mark:hover .bar,.mark:focus .bar{{opacity:.8}} .mark:focus-visible .hit-area{{stroke:var(--accent);stroke-width:1.5}}
.legend{{display:flex;flex-wrap:wrap;gap:16px;color:var(--ink2);font-size:13px;margin:10px 0 0}}
.sw{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}}
.sw.base{{background:var(--s1)}} .sw.hit{{background:var(--s2)}} .sw.flop{{background:var(--flop)}}
#tip{{position:fixed;pointer-events:none;z-index:9;background:var(--surface);color:var(--ink);border:1px solid var(--line);
border-radius:10px;padding:10px 12px;font-size:12px;max-width:300px;box-shadow:0 8px 24px rgba(0,0,0,.18);opacity:0;transition:opacity .12s}}
#tip .tt{{font-weight:600;margin-bottom:2px}} #tip .td{{color:var(--muted);margin-bottom:6px}}
#tip .tr{{display:flex;justify-content:space-between;gap:14px}} #tip .tr b{{font-variant-numeric:tabular-nums}} #tip .tr span{{color:var(--ink2)}}
.tips{{list-style:none;padding:0;margin:8px 0 0;display:grid;gap:10px}}
.tips li{{display:grid;gap:2px;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--bg)}}
.tips li span{{color:var(--ink2);font-size:14px}} .tips li em{{color:var(--muted);font-size:12px;font-style:normal}}
.tablewrap{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th button{{all:unset;cursor:pointer;color:var(--ink2);font-weight:600}} th button:focus-visible{{outline:2px solid var(--accent)}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
tr.hit td:first-child{{box-shadow:inset 3px 0 var(--s2)}} tr.flop td{{color:var(--muted)}}
.corrbar{{display:inline-block;width:120px;height:8px;background:var(--grid);border-radius:4px;position:relative;overflow:hidden}}
.corrbar i{{position:absolute;left:0;top:0;bottom:0;width:var(--w);border-radius:4px}} .corrbar .pos{{background:var(--s1)}} .corrbar .neg{{background:var(--neg)}}
details.auto{{margin-top:14px}} details.auto summary{{cursor:pointer;color:var(--ink2);font-size:14px}}
.pair{{display:inline-block;width:110px;height:8px;background:var(--grid);border-radius:4px;position:relative;overflow:hidden}}
.pair i{{position:absolute;left:0;top:0;bottom:0;width:var(--w);border-radius:4px}} .pair .yt{{background:var(--s1)}} .pair .ig{{background:var(--s3)}}
.sw.ig{{background:var(--s3)}}
footer{{color:var(--muted);font-size:12px;margin-top:28px}}
@media (max-width:600px){{.kpi-v{{font-size:24px}} .card{{padding:16px}}}}
</style><main>
<header>
<div class="eyebrow">@{acct} · {period} · coletado em {collected}</div>
<h1>{headline}</h1>
<p class="lead">{summary}</p>
</header>
<div class="kpis">{kpis}</div>
{acct_note}
{prev}
<section class="card">
<h2>Views de cada vídeo</h2>
<p class="sub">Em ordem de publicação. Passe o mouse (ou use Tab) em cada barra para ver as métricas.</p>
{timeline}
{legend}
</section>

<h2 style="margin-top:28px">O que os números mostram</h2>
<p class="sub">Confiança pela quantidade de vídeos por grupo: forte (5+), média (3–4), fraca (2). Comparações por grupo usam {basis}.</p>
<div class="findings">{findings}</div>

<section class="card">
<h2>O que mudar</h2>
<ul class="tips">{tips}</ul>
{auto}
</section>
{nxt}
{exp}

<h2 style="margin-top:28px">Qual tema, gancho e formato rende mais</h2>
<div class="grid2">{dims}</div>

<div class="grid2" style="margin-top:16px">
<section class="card"><h3>Continuaram assistindo × views</h3><p class="sub">Cada ponto é um vídeo. “Continuaram assistindo” = quem não deslizou no feed de Shorts.</p>{sc1}{legend}</section>
<section class="card"><h3>% assistida × views</h3><p class="sub">Porcentagem média do vídeo que cada view assistiu.</p>{sc2}{legend}</section>
</div>
{cross}

<section class="card">
<h2>O que anda junto com mais views</h2>
<p class="sub">Correlação de Spearman (−1 a +1). Com poucos vídeos, só valores acima de ±0,5 merecem atenção, e correlação não prova causa.</p>
<div class="tablewrap"><table class="plain"><thead><tr><th>Característica</th><th class="num">ρ</th><th></th><th>Força</th></tr></thead><tbody>{corr}</tbody></table></div>
</section>

<section class="card">
<h2>Todos os vídeos</h2>
<p class="sub">Clique no título da coluna para ordenar. Estouro: {hit_rule}. Não distribuído: {flop_rule}.</p>
<div class="tablewrap"><table id="posts"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
</section>

<section class="card">
<h2>Limites desta análise</h2>
<ul>{cav}<li>Views de Shorts têm cauda longa: poucos vídeos somam a maior parte. Por isso a página usa a mediana, não a média.</li>
<li>Os números vêm do Modo avançado do YouTube Studio (todo o período) no dia da coleta. Vídeos recentes ainda estão crescendo.</li></ul>
</section>
<footer>Gerado pela skill youtube-insights · dados lidos só para análise, nada foi alterado no canal.</footer>
</main>
<div id="tip" role="tooltip"></div>
<script>
(() => {{
  const tip = document.getElementById('tip');
  const show = (el, x, y) => {{
    let d; try {{ d = JSON.parse(el.dataset.tip); }} catch (e) {{ return; }}
    tip.replaceChildren();
    const t = document.createElement('div'); t.className = 'tt'; t.textContent = d.t; tip.append(t);
    if (d.d) {{ const s = document.createElement('div'); s.className = 'td'; s.textContent = d.d; tip.append(s); }}
    for (const [k, v] of d.rows || []) {{
      const r = document.createElement('div'); r.className = 'tr';
      const a = document.createElement('span'); a.textContent = k; const b = document.createElement('b'); b.textContent = v;
      r.append(a, b); tip.append(r);
    }}
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 14)) + 'px';
    tip.style.top = (y + h + 20 > window.innerHeight ? y - h - 14 : y + 14) + 'px';
    tip.style.opacity = 1;
  }};
  document.querySelectorAll('[data-tip]').forEach(el => {{
    el.addEventListener('pointermove', e => show(el, e.clientX, e.clientY));
    el.addEventListener('pointerleave', () => tip.style.opacity = 0);
    el.addEventListener('focus', () => {{ const r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top); }});
    el.addEventListener('blur', () => tip.style.opacity = 0);
  }});
  const table = document.getElementById('posts');
  table.querySelectorAll('th').forEach((th, i) => th.querySelector('button').addEventListener('click', () => {{
    const asc = th.dataset.dir !== 'asc'; th.dataset.dir = asc ? 'asc' : 'desc';
    const rows = [...table.tBodies[0].rows];
    rows.sort((a, b) => {{
      const x = a.cells[i].dataset.v, y = b.cells[i].dataset.v;
      const nx = parseFloat(x), ny = parseFloat(y);
      const c = (!isNaN(nx) && !isNaN(ny)) ? nx - ny : x.localeCompare(y, 'pt');
      return asc ? c : -c;
    }});
    table.tBodies[0].append(...rows);
  }}));
}})();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--notes")
    ap.add_argument("--out", required=True)
    ap.add_argument("--standalone", action="store_true",
                    help="documento completo (<!doctype>…) para abrir direto do disco; sem a flag, sai no formato do Artifact")
    a = ap.parse_args()
    an = load_json(a.analysis)
    notes = load_json(a.notes) if a.notes and Path(a.notes).exists() else {}
    page = build(an, notes)
    if a.standalone:
        page = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
                + page.replace("<main>", "</head><body><main>", 1) + "</body></html>")
    Path(a.out).write_text(page, encoding="utf-8")
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
