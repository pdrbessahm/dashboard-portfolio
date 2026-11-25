// Print de pagina inteira via CDP no Chromium do cache do Playwright.
// Uso: node prints/print.mjs <chrome> <pagina dentro de dist/, ex.: index.html> <saida.png> [largura] [projeto|dist] [altura] [seletor]
// Com "projeto", a pagina e relativa a raiz do repositorio (ex.: prototipo/sequencial.html); "dist" e o padrao.
// Com "altura", captura so essa faixa do alto da pagina (ex.: 200 para conferir a barra do topo); 0 = sem limite.
// Com "seletor" (CSS), captura so a area que cobre os elementos encontrados (ex.: ".topo, .heroi" ou "#projetos").
// Largura padrao 390 (celular); a partir de 1024 (ex.: 1440) emula desktop, sem toque.
// Serve dist/ por HTTP: o site usa caminhos absolutos (/static/...), que nao funcionam em file://.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { dirname, extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const [chrome, pagina, saida, larguraArg, raizArg, alturaArg, seletor] = process.argv.slice(2);
// raiz opcional: "projeto" serve a raiz do repositorio (para o prototipo/, que usa ../static/)
const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const DIST = raizArg === 'projeto' ? RAIZ : join(RAIZ, 'dist');
const TIPOS = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.pdf': 'application/pdf',
  '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const servidor = createServer((req, res) => {
  let caminho = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname));
  if (caminho.endsWith('/')) caminho += 'index.html';
  try {
    const corpo = readFileSync(join(DIST, caminho));
    res.writeHead(200, { 'Content-Type': TIPOS[extname(caminho)] ?? 'application/octet-stream' }).end(corpo);
  } catch {
    res.writeHead(404).end();
  }
});
await new Promise((ok) => servidor.listen(0, '127.0.0.1', ok));
const url = `http://127.0.0.1:${servidor.address().port}/${pagina.replace(/^\/+/, '')}`;
const perfil = mkdtempSync(join(tmpdir(), 'chrome-print-'));
const proc = spawn(chrome, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${perfil}`,
  '--no-first-run', '--no-default-browser-check', '--hide-scrollbars',
  // o Ubuntu bloqueia o sandbox do Chromium baixado; aqui ele so abre o proprio site, em arquivo local
  '--no-sandbox', 'about:blank']);

const wsBrowser = await new Promise((ok, erro) => {
  let buf = '';
  proc.stderr.on('data', (d) => {
    buf += d;
    const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
    if (m) ok(m[1]);
  });
  proc.on('exit', () => erro(new Error('chrome saiu: ' + buf)));
});

const porta = new URL(wsBrowser).port;
const alvos = await (await fetch(`http://127.0.0.1:${porta}/json/list`)).json();
const ws = new WebSocket(alvos.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((ok) => ws.addEventListener('open', ok));

let seq = 0;
const pendentes = new Map();
const ouvintes = new Map();
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pendentes.has(msg.id)) {
    const { ok, erro } = pendentes.get(msg.id);
    pendentes.delete(msg.id);
    msg.error ? erro(new Error(msg.error.message)) : ok(msg.result);
  } else if (msg.method && ouvintes.has(msg.method)) {
    ouvintes.get(msg.method)(msg.params);
  }
});
const cdp = (method, params = {}) => new Promise((ok, erro) => {
  const id = ++seq;
  pendentes.set(id, { ok, erro });
  ws.send(JSON.stringify({ id, method, params }));
});
const evento = (method) => new Promise((ok) => ouvintes.set(method, ok));

const LARGURA = Number(larguraArg ?? 390), ESCALA = 2;
const DESKTOP = LARGURA >= 1024;
const ALTURA = DESKTOP ? 900 : 844;
await cdp('Page.enable');
await cdp('Emulation.setDeviceMetricsOverride', { width: LARGURA, height: ALTURA, deviceScaleFactor: ESCALA, mobile: !DESKTOP });
await cdp('Emulation.setTouchEmulationEnabled', { enabled: !DESKTOP });
const carregou = evento('Page.loadEventFired');
await cdp('Page.navigate', { url });
await carregou;
await cdp('Runtime.evaluate', { expression: 'document.fonts.ready', awaitPromise: true });
// imagens com loading="lazy" abaixo da dobra nao carregam sem rolagem: forca o carregamento e espera todas
await cdp('Runtime.evaluate', { awaitPromise: true, expression: `Promise.all([...document.images].map((img) => {
  img.loading = 'eager';
  return img.complete ? null : new Promise((ok) => { img.addEventListener('load', ok); img.addEventListener('error', ok); });
}))` });
await new Promise((ok) => setTimeout(ok, 800));

const { cssContentSize } = await cdp('Page.getLayoutMetrics');
// faixa vertical a capturar: a pagina toda ou, com seletor, do topo do primeiro elemento ao fim do ultimo
let topo = 0, fim = Math.ceil(cssContentSize.height);
if (seletor) {
  const { result } = await cdp('Runtime.evaluate', { returnByValue: true, expression: `(() => {
    const els = [...document.querySelectorAll(${JSON.stringify(seletor)})];
    if (!els.length) return null;
    const r = els.map((el) => el.getBoundingClientRect());
    return [Math.min(...r.map((x) => x.top)) + scrollY, Math.max(...r.map((x) => x.bottom)) + scrollY];
  })()` });
  if (!result.value) throw new Error(`nenhum elemento para o seletor ${seletor}`);
  [topo, fim] = [Math.floor(result.value[0]), Math.ceil(result.value[1])];
}
const limite = Number(alturaArg) > 0 ? Number(alturaArg) : Infinity;
const altura = Math.min(fim - topo, limite);
const { data } = await cdp('Page.captureScreenshot', {
  format: 'png', captureBeyondViewport: true,
  clip: { x: 0, y: topo, width: LARGURA, height: altura, scale: 1 },
});
writeFileSync(saida, Buffer.from(data, 'base64'));
console.log(`ok: ${saida} (${LARGURA}x${altura} css, escala ${ESCALA}, largura do conteudo ${Math.ceil(cssContentSize.width)})`);
if (cssContentSize.width > LARGURA + 0.5) {
  // pagina mais larga que a tela: lista os elementos que passam da borda direita (fora de area com rolagem propria)
  const { result } = await cdp('Runtime.evaluate', { returnByValue: true, expression: `(() => {
    const rola = (el) => { for (let p = el.parentElement; p; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return true; } return false; };
    return [...document.querySelectorAll('body *')]
      .filter((el) => el.getBoundingClientRect().right > ${LARGURA} + 0.5 && !rola(el))
      .slice(0, 12)
      .map((el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '') + ' ate ' + Math.round(el.getBoundingClientRect().right) + 'px');
  })()` });
  console.log('AVISO: conteudo mais largo que a tela:\n  ' + result.value.join('\n  '));
}
ws.close();
proc.kill();
servidor.close();
