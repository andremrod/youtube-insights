# Como ler as métricas do YouTube (base para as dicas)

Atualizado em 2026-11-10. Use só o que está marcado. Não invente benchmark.

| Métrica no Studio | Campo | O que diz |
|---|---|---|
| Continuaram assistindo (Viewed vs. swiped away) | `stayed` | Só para Shorts: % de quem viu o Short no feed e não deslizou. É o primeiro filtro do feed de Shorts. |
| Porcentagem visualizada média | `retention` | Quanto do vídeo cada view assistiu. Em Shorts, pode passar de 100% (replay). |
| Duração média da visualização | `avg_view_s` | Segundos por view. |
| Taxa de cliques na miniatura (CTR) | `ctr` | Pesa mais em vídeos longos e na busca. Em Shorts, o feed não usa miniatura. |
| Impressões de miniatura | `impressions` | Só conta onde a miniatura aparece (busca, navegação). Não mede o alcance no feed de Shorts. |
| Inscritos | `subs` | Saldo de inscritos atribuído ao vídeo. |
| Fontes de tráfego | `account.json → traffic_sources` | Se quase tudo vem do "Feed dos Shorts", o resultado depende de segurar o polegar. A parcela de "Pesquisa do YouTube" mostra o peso do título. |

Leitura para canais pequenos:
- Use a mediana, não a média.
- Estouro (≥2× a mediana) e flop (<25%) ficam à parte.
- Sempre diga o n e confira se duas características não se misturam (dia de estreia, uploads no mesmo dia).
- Mesmo vídeo com resultados opostos no YouTube e no Instagram é sinal de distribuição, não de tema.
