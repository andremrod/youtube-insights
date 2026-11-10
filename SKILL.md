---
name: youtube-insights
description: Analisa as métricas dos vídeos e Shorts já publicados no canal do YouTube do usuário para descobrir o que deu certo — qual tema, formato de título, gancho, duração, dia, quantidade de uploads por dia e formato rende mais views, "continuaram assistindo" (não deslizaram), % assistida, inscritos e CTR — e entrega gráficos (página Artifact) com dicas e ideias de próximos vídeos baseadas nos números. Lê os dados pelo Claude in Chrome no YouTube Studio (Modo avançado e lista de Conteúdo) da sessão logada, ou de um CSV exportado; compara o mesmo vídeo com o Instagram (skill instagram-insights) e com a rodada anterior. Use quando o usuário pedir para analisar o YouTube, o canal, os Shorts, ver métricas ou desempenho dos vídeos, "o que deu certo", qual título ou tema funciona, por que um vídeo flopou ou bombou, ou dicas para crescer no YouTube com base nos próprios dados.
---

# YouTube Insights

Pasta das rodadas: `~/Documents/youtube-insights/runs/AAAA-MM-DD/`. Scripts em `scripts/` (Python 3.12+, só biblioteca padrão; `ffprobe` opcional).
Funciona como a skill `instagram-insights`: coletar → normalizar → marcar → analisar → interpretar → página.
Escreva para o usuário em português simples. Só leitura: nunca edite título, publique, apague ou mude configurações no Studio sem o usuário pedir.

## 1. Coletar (Claude in Chrome, só leitura)
Carregue a skill `chrome-browser`. Se houver mais de um Chrome conectado, pergunte qual usar. Abra uma aba nova em `https://studio.youtube.com/` e anote o ID do canal (`UC…`) que aparece na URL.

1. **Métricas por vídeo (Modo avançado).** Abra a URL abaixo, trocando `<ID>`:
   ```
   https://studio.youtube.com/channel/<ID>/analytics/tab-overview/period-default/explore?entity_type=CHANNEL&entity_id=<ID>&time_period=lifetime&explore_type=TABLE_AND_CHART&metric=VIEWS&granularity=DAY&t_metrics=VIEWS&t_metrics=WATCH_TIME&t_metrics=AVERAGE_WATCH_TIME&t_metrics=AVERAGE_WATCH_PERCENTAGE&t_metrics=SUBSCRIBERS_NET_CHANGE&t_metrics=VIDEO_THUMBNAIL_IMPRESSIONS&t_metrics=VIDEO_THUMBNAIL_IMPRESSIONS_VTR&t_metrics=RATINGS_LIKES&t_metrics=COMMENTS&t_metrics=SHARINGS&t_metrics=SHORTS_FEED_IMPRESSIONS_VTR&dimension=VIDEO&o_column=VIEWS&o_direction=ANALYTICS_ORDER_DIRECTION_DESC
   ```
   - O `get_page_text` não lê essa página. Rode `collect/analytics_table.js` com `javascript_tool`.
   - Depois leia `window.__yt.slice(0,7).join('\n')`, `slice(7,14)` e assim por diante. O `javascript_tool` corta respostas acima de cerca de 1 KB.
   - Salve como `raw_analytics.json`: `{"collected_at","period","headers":[...],"rows":["linha", ...]}`.
   - Com mais de ~50 vídeos, a tabela pagina. Nesse caso, o ícone de download do Modo avançado gera um CSV. Baixar exige a permissão do usuário; prefira que ele baixe e diga o caminho. O parser aceita o CSV pelo `--analytics`.
2. **Datas, descrições e IDs (Conteúdo).**
   - Abra `https://studio.youtube.com/channel/<ID>/videos/short` e leia com `get_page_text`. Salve o trecho dos vídeos em `raw_content_shorts.txt`.
   - Se o canal tiver vídeos longos, faça o mesmo com `/videos/upload` e salve em `raw_content_videos.txt`.
   - Rode `collect/content_ids.js` e salve a saída em `raw_ids.txt`.
3. **Fontes de tráfego.** Abra a mesma URL do Modo avançado com `dimension=TRAFFIC_SOURCE_TYPE` e só `t_metrics=VIEWS`. Leia as linhas por JS (título | views). Salve em `account.json` como `"traffic_sources": {"Feed dos Shorts": n, ...}`, junto com `subscribers`.

Não use a API do YouTube nem peça token.

## 2. Normalizar e marcar
```
S=~/.claude/skills/youtube-insights/scripts; D=~/Documents/youtube-insights/runs/AAAA-MM-DD
python3 $S/collect_parse.py --analytics $D/raw_analytics.json --content short:$D/raw_content_shorts.txt [--content video:$D/raw_content_videos.txt] --ids $D/raw_ids.txt --channel <nome> --collected-at <ISO> --out $D/videos.json
python3 $S/tag_videos.py --posts $D/videos.json --out $D/tags.json [--videos "<pasta dos MP4>"] [--keep <rodada anterior>/tags.json]
```
Revise `tags.json`:
- corrija `theme`, `era`, `region`, `title_format` e `hook_type` (`?` significa não deduzido);
- `extra` vira uma dimensão a mais;
- marque `reviewed: true`.

Os temas ficam em `references/themes.json`. Mantenha esse arquivo igual ao do Instagram.

## 3. Analisar
```
python3 $S/analyze.py --videos $D/videos.json --tags $D/tags.json --account $D/account.json \
   [--cross ~/Documents/instagram-insights/runs/<mais recente>/analysis.json] [--previous <rodada anterior>/analysis.json] --out $D/analysis.json
```
- Use `--cross` sempre que houver rodada do Instagram: ele casa o mesmo vídeo nas duas plataformas.
- Regras fixas:
  - estouro = views ≥ 2× a mediana; flop = menos de 25% da mediana;
  - flops ficam fora das comparações por grupo;
  - confiança: 5+ forte, 3–4 média, 2 fraca.

## 4. Interpretar (`notes.json`, mesmo formato da skill do Instagram)
Leia `analysis.json` e `references/playbook.md`. Confira **variáveis misturadas** antes de afirmar algo. Exemplo: todos os títulos sem pergunta saíram no primeiro dia. Nesse caso, compare de novo deixando o primeiro dia de fora, e diga isso no texto.

Toda dica precisa citar o número que a sustenta. Não invente benchmark. Confira se há vídeos prontos e não publicados nas pastas de vídeo e sugira títulos em pergunta para eles.

## 5. Entregar
1. `python3 $S/render_report.py --analysis $D/analysis.json --notes $D/notes.json --out $D/report.html`. Use `--standalone` para abrir direto do disco.
2. Carregue `artifact-design` e publique com Artifact (icon `chart`). Nas próximas rodadas, publique na mesma URL.
3. Responda no chat com os achados principais, as 3 dicas de maior impacto e o link. Feche as abas que abriu.

## Testes
`python3 -m unittest discover -s ~/.claude/skills/youtube-insights/tests`
