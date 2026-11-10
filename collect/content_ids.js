// YouTube Studio → Conteúdo (Vídeos ou Shorts). Rode com javascript_tool. Só lê.
// Devolve "id do vídeo|data|primeiros 40 caracteres do título", uma linha por vídeo da página atual.
// Se a lista tiver mais de ~25 vídeos, leia em partes: troque o slice(0, 25) por slice(25, 50) etc.
[...document.querySelectorAll('ytcp-video-row')].slice(0, 25).map((r) => {
  const a = r.querySelector('a[href*="/video/"]');
  const id = a ? a.href.match(/video\/([^/]+)/)[1] : '?';
  const date = (r.querySelector('.tablecell-date')?.innerText || '').split('\n')[0].trim();
  return [id, date, (r.querySelector('#video-title')?.innerText || '').slice(0, 40)].join('|');
}).join('\n');
