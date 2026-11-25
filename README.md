# Portfólio de Pedro Henrique Bessa Maia

Site estático do portfólio de analista de dados.
É gerado em Python (Jinja2 e Plotly) e não tem backend, banco nem segredo.

## Como rodar localmente

Precisa de Python 3.12 ou mais novo.

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python site.py serve
```

Abra `http://localhost:8000`.
O comando gera a pasta `dist/` e serve o site a partir dela.

Outros comandos:

- `python site.py build`: só gera a pasta `dist/`.
- `python site.py importar-painel <origem.html> <nome>`: traz um painel HTML já anonimizado para `paineis/<nome>/`, troca o plotly.js embutido pelo do site e recusa o arquivo se achar dado sensível.
- `python favicon/opcoes.py` e depois `node favicon/gerar.mjs <caminho do chrome>`: refazem o favicon (monograma "pb" em JetBrains Mono).
  O primeiro grava os SVG (precisa de `pip install fonttools brotli`), o segundo gera no Chromium os PNG de 32 e 180 px e o `favicon.ico` em `static/favicon/`.
  O build copia o `favicon.ico` também para a raiz do `dist/`.
- `python site.py verificar`: procura em `dados/`, `conteudo/`, `paineis/`, `static/` e `dist/` CPF, CNPJ, telefone, e-mail de terceiros e os termos da lista de proibidos, e lista o que ainda está pendente.

A lista de termos proibidos e o de-para da anonimização ficam fora do repositório.
Aponte a variável `PORTFOLIO_PRIVADO` para a pasta que contém `termos-proibidos.txt` (um termo por linha).
Sem ela, o `build` avisa e o `verificar` falha.

## Estrutura

```
site.py        build, serve e verificar
conteudo/      texto de cada página (um arquivo .toml por projeto, mais o perfil)
dados/         só JSON anonimizado e agregado
paineis/       painéis HTML já anonimizados (um por pasta, com README)
anonimizacao/  scripts que leem a origem e gravam em dados/
templates/     HTML (Jinja2)
static/        CSS, JavaScript e, depois, prints e o CV em PDF
dist/          site gerado (fora do repositório)
```

## Publicação

O repositório é `pdrbessahm/dashboard-portfolio` (privado).
O site fica no Cloudflare Pages, ligado ao repositório: a cada push na `main`, o Cloudflare gera o `dist/` e publica.
Push em outro branch vira uma prévia com endereço próprio, sem mexer no site no ar.
Antes de cada push, rode `python site.py verificar` aqui (com `PORTFOLIO_PRIVADO`): a lista de termos proibidos não vai para o GitHub.

Para ligar o Cloudflare (uma vez):

1. No painel do Cloudflare, em Workers & Pages > Create > Pages > Connect to Git, autorize o GitHub e escolha `pdrbessahm/dashboard-portfolio` (o repositório privado funciona).
2. Configuração do build:
   - Production branch: `main`
   - Framework preset: None
   - Build command: `pip install -r requirements.txt && python site.py build` (sai o visual publicado, `TEMA_PUBLICADO` no `site.py`, hoje a vitrine)
   - Build output directory: `dist`
3. Save and Deploy. O endereço sai como `<nome-do-projeto>.pages.dev`.
4. Domínio próprio: em Custom domains no projeto do Pages.

O Python do build vem do `.python-version` (3.12).
O Pages usa o `404.html` da raiz como página de erro sozinho, sem configuração.

## O que o servidor precisa

- Hospedagem de arquivos estáticos com HTTPS (por exemplo Cloudflare Pages).
- Nenhum runtime, banco ou variável secreta.
- Publicar é copiar o conteúdo de `dist/` para a raiz do site.
  Configure `404.html` como página de erro.
- Para gerar o `dist/`: Python 3.12 ou mais novo e `pip install -r requirements.txt`.
