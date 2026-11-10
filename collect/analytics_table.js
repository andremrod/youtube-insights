// YouTube Studio → Estatísticas → Modo avançado (tabela por Conteúdo). Rode com javascript_tool.
// Só lê. Guarda as linhas em window.__yt e devolve os cabeçalhos e a quantidade.
// O javascript_tool corta respostas longas (~1 KB): depois leia em partes com
//   window.__yt.slice(0, 7).join('\n')   →   slice(7, 14)   →   ...
// Cada linha (separada por TAB): título (até 90 caracteres), duração, métricas na ordem dos cabeçalhos (sem "Data de publicação").
await (async () => {
  for (let i = 0; i < 20 && !document.querySelector('yta-explore-table-row .debug-metric-value'); i++)
    await new Promise((r) => setTimeout(r, 500));
  const T = document.querySelector('yta-explore-table');
  if (!T) return 'Tabela não encontrada: abra o Modo avançado com Detalhamento = Conteúdo.';
  const headers = [...T.querySelectorAll('.debug-metric-title')].map((e) => e.innerText.replace(/\s+/g, ' ').trim());
  window.__yt = [...T.querySelectorAll('yta-explore-table-row')].map((r) => {
    const title = r.querySelector('.debug-dimension-value')?.innerText.trim() || 'Total';
    const dur = r.querySelector('ytcp-badge .label')?.innerText.trim() || '';
    const vals = [...r.querySelectorAll('.debug-metric-value')].map((e) => e.innerText.trim());
    return [title.slice(0, 90), dur, ...vals].join('\t');
  });
  return JSON.stringify({ headers, linhas: window.__yt.length });
})();
