// Print em faixas, para conferir texto de perto (o print inteiro do celular fica pequeno demais para ver espaçamento).
// Uso: node prints/recorte.mjs <chrome> <pagina relativa a raiz do projeto> <prefixo da saida> <largura> <altura da faixa>
// Gera <prefixo>-0.png, <prefixo>-1.png, ... cobrindo a pagina inteira. Serve a raiz do projeto por HTTP.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { dirname, extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const [chrome, pagina, prefixo, larguraArg, faixaArg] = process.argv.slice(2);
const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const TIPOS = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
const servidor = createServer((req, res) => {
  const caminho = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname));
  try {
    res.writeHead(200, { 'Content-Type': TIPOS[extname(caminho)] ?? 'application/octet-stream' }).end(readFileSync(join(RAIZ, caminho)));
  } catch {
    res.writeHead(404).end();
  }
});
await new Promise((ok) => servidor.listen(0, '127.0.0.1', ok));
const url = `http://127.0.0.1:${servidor.address().port}/${pagina.replace(/^\/+/, '')}`;
const proc = spawn(chrome, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${mkdtempSync(join(tmpdir(), 'chrome-recorte-'))}`,
  '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--no-sandbox', 'about:blank']);
const wsBrowser = await new Promise((ok, erro) => {
  let buf = '';
  proc.stderr.on('data', (d) => {
    buf += d;
    const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
    if (m) ok(m[1]);
  });
  proc.on('exit', () => erro(new Error('chrome saiu: ' + buf)));
});
const alvos = await (await fetch(`http://127.0.0.1:${new URL(wsBrowser).port}/json/list`)).json();
const ws = new WebSocket(alvos.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((ok) => ws.addEventListener('open', ok));

let seq = 0;
const pendentes = new Map();
const ouvintes = new Map();
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pendentes.has(msg.id)) {
    pendentes.get(msg.id)(msg.result);
    pendentes.delete(msg.id);
  } else if (msg.method && ouvintes.has(msg.method)) {
    ouvintes.get(msg.method)(msg.params);
  }
});
const cdp = (method, params = {}) => new Promise((ok) => {
  const id = ++seq;
  pendentes.set(id, ok);
  ws.send(JSON.stringify({ id, method, params }));
});

const LARGURA = Number(larguraArg), FAIXA = Number(faixaArg), DESKTOP = LARGURA >= 1024;
await cdp('Page.enable');
await cdp('Emulation.setDeviceMetricsOverride', { width: LARGURA, height: DESKTOP ? 900 : 844, deviceScaleFactor: 2, mobile: !DESKTOP });
await cdp('Emulation.setTouchEmulationEnabled', { enabled: !DESKTOP });
const carregou = new Promise((ok) => ouvintes.set('Page.loadEventFired', ok));
await cdp('Page.navigate', { url });
await carregou;
await cdp('Runtime.evaluate', { expression: 'document.fonts.ready', awaitPromise: true });
await new Promise((ok) => setTimeout(ok, 800));

const { cssContentSize } = await cdp('Page.getLayoutMetrics');
const altura = Math.ceil(cssContentSize.height);
let n = 0;
for (let y = 0; y < altura; y += FAIXA, n++) {
  const { data } = await cdp('Page.captureScreenshot', {
    format: 'png', captureBeyondViewport: true,
    clip: { x: 0, y, width: LARGURA, height: Math.min(FAIXA, altura - y), scale: 1 },
  });
  writeFileSync(`${prefixo}-${n}.png`, Buffer.from(data, 'base64'));
}
console.log(`ok: ${n} faixas de ${FAIXA}px (${LARGURA}x${altura} css)`);
ws.close();
proc.kill();
servidor.close();
