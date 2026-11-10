# YouTube Insights

[![tests](https://github.com/andremrod/youtube-insights/actions/workflows/tests.yml/badge.svg)](https://github.com/andremrod/youtube-insights/actions/workflows/tests.yml)

Descobre **o que deu certo nos seus Shorts e vídeos do YouTube**: qual tema, formato de título, abertura, duração, dia e quantidade de uploads por dia trazem mais views, mais gente que continua assistindo em vez de deslizar, maior porcentagem assistida e mais inscritos. O resultado é uma página com gráficos e dicas, todas baseadas nos números do próprio canal.

- **Lê os dados que você já tem.** Usa o Modo avançado e a lista de Conteúdo do YouTube Studio (ou o CSV exportado). Não precisa de API nem token.
- **Feito para Shorts.** Usa “Continuaram assistindo” (quem não deslizou), % assistida e fontes de tráfego, além de CTR e impressões para vídeos longos.
- **Compara com o Instagram.** Com uma análise da skill [instagram-insights](https://github.com/andremrod/instagram-insights), casa o mesmo vídeo nas duas plataformas e mostra onde cada um foi melhor.
- **Não engana com amostra pequena.** Usa mediana, separa estouros (≥2× a mediana) e flops (<25%) e mostra o nível de confiança de cada achado.
- **Só Python, biblioteca padrão.**
- **Funciona como skill do Claude Code.** O Claude coleta os dados no seu navegador (só leitura), marca os temas, escreve a interpretação e publica a página.

*English: a Claude Code skill and stdlib-only Python toolkit that reads your YouTube Studio analytics (Advanced mode table, Content list or CSV export), tags each video (title format, hook, theme, era, duration…), finds what drives views, “stayed to watch”, average percentage viewed and subscribers, compares the same video against Instagram, and renders a self-contained HTML report with charts and data-backed tips. The report and texts are in Brazilian Portuguese.*

## Como funciona

| Etapa | O que faz |
|---|---|
| `collect/analytics_table.js` | Lê a tabela do Modo avançado do Studio (por vídeo) |
| `collect/content_ids.js` | Lê o ID, a data e o título de cada vídeo na lista de Conteúdo |
| `scripts/collect_parse.py` | Junta tabela, texto da lista de Conteúdo e IDs (ou CSV) em `videos.json` |
| `scripts/tag_videos.py` | Formato do título (pergunta, “Nome: explicação”, só o nome…), gancho da descrição, série, época, região, tema; casa cada vídeo com o MP4 pela duração |
| `scripts/analyze.py` | Estouros e flops, grupos por dimensão com *lift*, uploads no mesmo dia, fontes de tráfego, correlações, comparação com o Instagram, achados e dicas |
| `scripts/render_report.py` | Página HTML com KPIs, gráficos, comparação YouTube × Instagram, tabela ordenável, tema claro/escuro e tooltips |

## Rodar à mão

Requer Python 3.12+.

```bash
git clone https://github.com/andremrod/youtube-insights.git
cd youtube-insights
D=runs/$(date +%F); mkdir -p $D

# 1. salve os dados do Studio (veja SKILL.md) ou baixe o CSV do Modo avançado
python3 scripts/collect_parse.py --analytics $D/raw_analytics.json --content short:$D/raw_content_shorts.txt \
    --ids $D/raw_ids.txt --channel meu_canal --out $D/videos.json
#    com CSV: --analytics tabela.csv

# 2. marque os vídeos e revise tags.json
python3 scripts/tag_videos.py --posts $D/videos.json --out $D/tags.json

# 3. analise (opcional: --cross com a análise do Instagram) e gere a página
python3 scripts/analyze.py --videos $D/videos.json --tags $D/tags.json --out $D/analysis.json
python3 scripts/render_report.py --analysis $D/analysis.json --out $D/report.html --standalone
open $D/report.html
```

`runs/` está no `.gitignore` porque guarda dados do seu canal.

## Usar como skill do Claude Code

```bash
git clone https://github.com/andremrod/youtube-insights.git ~/.claude/skills/youtube-insights
```

Peça algo como *“analisa meu canal do YouTube e me diz o que deu certo”*. Com a extensão [Claude in Chrome](https://claude.com/chrome) conectada, o Claude:

1. abre o YouTube Studio na sua sessão e lê as métricas (só leitura);
2. roda os scripts e revisa as marcações;
3. escreve a interpretação, conferindo variáveis misturadas (por exemplo, o dia de estreia);
4. publica a página e responde com os principais achados.

O passo a passo está em [`SKILL.md`](SKILL.md).

## Limites

- A lista de Conteúdo do Studio dá a data de publicação sem a hora, então a análise não compara horários.
- Com poucos vídeos por grupo, os achados são pistas para testar.
- Como ler cada métrica: [`references/playbook.md`](references/playbook.md).

## Testes

```bash
python3 -m unittest discover -s tests -v
```

## Licença

[MIT](LICENSE)
