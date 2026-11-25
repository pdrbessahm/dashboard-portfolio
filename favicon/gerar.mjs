// Gera os PNG e o ICO do favicon a partir dos SVG, no Chromium do cache do Playwright.
// Uso: node favicon/gerar.mjs <chrome>
// Fontes: static/favicon/favicon.svg (32 px para cima), favicon/favicon-16.svg (desenho proprio da grade de 16 px)
// e favicon/apple-touch-icon.svg (tela inicial do iPhone).
// Saida em static/favicon/: favicon-32.png, apple-touch-icon.png e favicon.ico (16, 32 e 48 px);
// o build copia o favicon.ico tambem para a raiz do site, onde o navegador procura sem link.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Com [pasta] (ex.: static/favicon/opcoes/1-space-grotesk), le os tres SVG dessa pasta e grava tudo nela,
// inclusive o favicon-16.png de conferencia: e assim que se geram as opcoes de favicon/opcoes.py.
const [chrome, pastaArg] = process.argv.slice(2);
if (!chrome) throw new Error('uso: node favicon/gerar.mjs <chrome> [pasta]');
const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SAIDA = pastaArg ? resolve(RAIZ, pastaArg) : join(RAIZ, 'static', 'favicon');
const CONFERENCIA = pastaArg ? SAIDA : join(RAIZ, 'favicon');
const fonte = (caminho) => readFileSync(caminho, 'utf8');
const PRINCIPAL = fonte(join(SAIDA, 'favicon.svg'));
const PEQUENO = fonte(join(CONFERENCIA, 'favicon-16.svg'));
const APPLE = fonte(join(CONFERENCIA, 'apple-touch-icon.svg'));

const perfil = mkdtempSync(join(tmpdir(), 'chrome-favicon-'));
const proc = spawn(chrome, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${perfil}`,
  '--no-first-run', '--no-default-browser-check', '--hide-scrollbars',
  // o Ubuntu bloqueia o sandbox do Chromium baixado; aqui ele so desenha SVG local
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
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pendentes.has(msg.id)) {
    const { ok, erro } = pendentes.get(msg.id);
    pendentes.delete(msg.id);
    msg.error ? erro(new Error(msg.error.message)) : ok(msg.result);
  }
});
const cdp = (method, params = {}) => new Promise((ok, erro) => {
  const id = ++seq;
  pendentes.set(id, { ok, erro });
  ws.send(JSON.stringify({ id, method, params }));
});

// fundo transparente: os cantos arredondados do favicon ficam vazados na aba
await cdp('Emulation.setDefaultBackgroundColorOverride', { color: { r: 0, g: 0, b: 0, a: 0 } });

async function png(svg, lado) {
  await cdp('Emulation.setDeviceMetricsOverride', { width: lado, height: lado, deviceScaleFactor: 1, mobile: false });
  const src = 'data:image/svg+xml;base64,' + Buffer.from(svg).toString('base64');
  const html = `<!doctype html><style>html,body{margin:0;background:transparent}img{display:block}</style>`
    + `<img src="${src}" width="${lado}" height="${lado}">`;
  const { frameId } = await cdp('Page.getFrameTree').then((r) => ({ frameId: r.frameTree.frame.id }));
  await cdp('Page.setDocumentContent', { frameId, html });
  await cdp('Runtime.evaluate', { awaitPromise: true,
    expression: 'new Promise((ok) => { const i = document.images[0]; i.complete ? ok() : i.onload = ok; })' });
  const { data } = await cdp('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: lado, height: lado, scale: 1 } });
  return Buffer.from(data, 'base64');
}

// ICO com as imagens em PNG dentro (aceito por todo navegador atual e pelo Windows desde o Vista)
function ico(imagens) {
  const cabecalho = Buffer.alloc(6);
  cabecalho.writeUInt16LE(0, 0);
  cabecalho.writeUInt16LE(1, 2);
  cabecalho.writeUInt16LE(imagens.length, 4);
  const entradas = [];
  let deslocamento = 6 + 16 * imagens.length;
  for (const { lado, dados } of imagens) {
    const e = Buffer.alloc(16);
    e.writeUInt8(lado >= 256 ? 0 : lado, 0);
    e.writeUInt8(lado >= 256 ? 0 : lado, 1);
    e.writeUInt8(0, 2);
    e.writeUInt8(0, 3);
    e.writeUInt16LE(1, 4);
    e.writeUInt16LE(32, 6);
    e.writeUInt32LE(dados.length, 8);
    e.writeUInt32LE(deslocamento, 12);
    deslocamento += dados.length;
    entradas.push(e);
  }
  return Buffer.concat([cabecalho, ...entradas, ...imagens.map((i) => i.dados)]);
}

const p16 = await png(PEQUENO, 16);
const p32 = await png(PRINCIPAL, 32);
const p48 = await png(PRINCIPAL, 48);
writeFileSync(join(SAIDA, 'favicon-32.png'), p32);
writeFileSync(join(SAIDA, 'apple-touch-icon.png'), await png(APPLE, 180));
writeFileSync(join(SAIDA, 'favicon.ico'), ico([{ lado: 16, dados: p16 }, { lado: 32, dados: p32 }, { lado: 48, dados: p48 }]));
// so para conferir o desenho de 16 px (nao vai para o site)
writeFileSync(join(CONFERENCIA, 'favicon-16.png'), p16);
console.log(`ok: ${SAIDA}/favicon-32.png, apple-touch-icon.png, favicon.ico (16, 32, 48)`);
ws.close();
proc.kill();
