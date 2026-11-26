"""Gera, serve e verifica o site do portfólio.

    python site.py build       gera a pasta dist/ com o visual publicado (TEMA_PUBLICADO, hoje a vitrine),
                               em português na raiz e em inglês em /en/
    python site.py build --tema editorial|painel|bento|misto|vitrine|nenhum
                               gera dist/ com outra variação de visual, para comparar (nenhum: o visual antigo)
    python site.py serve       gera e serve em http://localhost:8000 (aceita --tema também)
    python site.py verificar   procura dado sensível em dados/ e dist/ e lista as pendências
    python site.py importar-painel <origem.html> <nome>
                               traz um painel já anonimizado para paineis/<nome>/painel.html

O site só lê conteudo/ (texto), dados/ (JSON já anonimizado e agregado) e paineis/ (painéis HTML já anonimizados).
O texto em inglês fica em conteudo/en/: cada arquivo traz só os campos de texto do arquivo em português de mesmo nome,
e os rótulos dos gráficos em inglês ficam em conteudo/en/graficos.toml.
"""

import argparse
import contextvars
import hashlib
import inspect
import json
import os
import re
import shutil
import sqlite3
import sys
import tomllib
import unicodedata
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup, escape
from plotly.offline import get_plotlyjs
from pypdf import PdfReader
from pypdf.errors import PdfReadError

RAIZ = Path(__file__).resolve().parent
CONTEUDO = RAIZ / "conteudo"
DADOS = RAIZ / "dados"
TEMPLATES = RAIZ / "templates"
STATIC = RAIZ / "static"
PAINEIS = RAIZ / "paineis"
CONSULTAS = RAIZ / "consultas"
DIST = RAIZ / "dist"

# Pasta fora do repositório com o de-para da anonimização e a lista de termos proibidos.
VAR_PRIVADO = "PORTFOLIO_PRIVADO"
ARQUIVO_TERMOS = "termos-proibidos.txt"

EMAIL_PERMITIDO = "bessapedro500@gmail.com"

# Cores do gráfico: barras em cinza e a etapa final no tom de destaque, como os cartões da página inicial.
COR_SERIE = "#9aa1ab"
# Mesmo azul do --acento-escuro do site.css (o tom de destaque que funciona no fundo claro).
COR_DESTAQUE = "#1d4ed8"
TINTA = "#111418"
TINTA_SECUNDARIA = "#4a4f57"
GRADE = "#e3e2dc"
# Variações de visual em teste, cada uma num CSS próprio (static/css/tema-<nome>.css) aplicado por cima do site.css.
# Mesmo conteúdo e mesmos templates; sem --tema o site sai como sempre. cor: theme-color; fonte: a que vale pré-carregar.
TEMAS = {
    "editorial": {"cor": "#faf8f3", "fonte": "fraunces-latin-600-normal.woff2"},
    "painel": {"cor": "#0b0f14", "fonte": "jetbrains-mono-latin-400-normal.woff2"},
    "bento": {"cor": "#eceef1", "fonte": "space-grotesk-latin-600-normal.woff2"},
    "misto": {"cor": "#faf8f3", "fonte": "fraunces-latin-600-normal.woff2"},
    # A vitrine muda a estrutura da página inicial (topo com foto, sobre, áreas de interesse e grade de projetos),
    # então além do CSS tem moldura (layout) e página inicial (index) próprias; os estudos de caso usam a moldura dela.
    # idiomas: tem o botão de idioma e sai também em inglês, em /en/
    "vitrine": {"cor": "#ffffff", "fonte": "inter-latin-600-normal.woff2",
                "layout": "vitrine/base.html", "index": "vitrine/index.html", "idiomas": True},
}
# O visual que vai para o ar: o build sem --tema usa este, e o Cloudflare Pages roda o build sem --tema.
TEMA_PUBLICADO = "vitrine"
SEM_TEMA = "nenhum"

# Segunda série quando duas medidas dividem o gráfico: laranja, o par do azul que segue distinto no daltonismo.
COR_PAR = "#c2410c"
# Variação: vermelho para queda, azul para alta, cinza no zero.
DIVERGENTE = [[0, "#e34948"], [0.5, "#f0efec"], [1, "#2a78d6"]]


# ---------------------------------------------------------------- idiomas

# raiz: prefixo dos endereços; html: atributo lang e hreflang; og: og:locale.
# O português é a fonte: o inglês só traduz texto e não tem página que o português não tenha.
LINGUAS = {
    "pt": {"raiz": "", "html": "pt-BR", "og": "pt_BR"},
    "en": {"raiz": "/en", "html": "en", "og": "en_US"},
}
CONTEUDO_EN = CONTEUDO / "en"
LINGUA = contextvars.ContextVar("lingua", default="pt")
# rótulos de gráfico pedidos no build em inglês sem tradução em conteudo/en/graficos.toml
SEM_TRADUCAO = set()


@contextmanager
def em_lingua(lingua):
    marca = LINGUA.set(lingua)
    try:
        yield
    finally:
        LINGUA.reset(marca)


def eh_pt():
    return LINGUA.get() == "pt"


ROTULO_LOJA = re.compile(r"^Loja ([A-Z])$")
ROTULO_ITEM = re.compile(r"^(.+) (\d+)$")


def tr(texto):
    """Rótulo de gráfico no idioma do build. Em português devolve o próprio texto.

    Em inglês procura em conteudo/en/graficos.toml; "Loja B" vira "Store B" e "Combo 01" traduz só o tipo.
    O que não achar fica em SEM_TRADUCAO e o build em inglês falha.
    """
    if eh_pt():
        return texto
    rotulos = rotulos_en()
    if texto in rotulos:
        return rotulos[texto]
    if m := ROTULO_LOJA.match(texto):
        return f"Store {m.group(1)}"
    if (m := ROTULO_ITEM.match(texto)) and m.group(1) in rotulos:
        return f"{rotulos[m.group(1)]} {m.group(2)}"
    SEM_TRADUCAO.add(texto)
    return texto


_ROTULOS_EN = {}


def rotulos_en():
    if not _ROTULOS_EN:
        _ROTULOS_EN.update(carregar_toml(CONTEUDO_EN / "graficos.toml")["rotulos"])
    return _ROTULOS_EN


# ---------------------------------------------------------------- conteúdo

def carregar_toml(caminho):
    with open(caminho, "rb") as f:
        return tomllib.load(f)


def mesclar(base, traducao, caminho):
    """Põe o texto traduzido por cima do arquivo em português.

    Tabela entra chave a chave; lista de tabelas entra item a item (precisa ter o mesmo tamanho);
    o resto (texto, lista de textos) é trocado inteiro. Chave que o português não tem é erro de digitação.
    """
    if isinstance(base, dict) and isinstance(traducao, dict):
        sobra = sorted(set(traducao) - set(base))
        if sobra:
            sys.exit(f"{caminho}: chave que o português não tem: {', '.join(sobra)}")
        return {k: mesclar(v, traducao[k], f"{caminho}.{k}") if k in traducao else v for k, v in base.items()}
    if isinstance(base, list) and base and isinstance(base[0], dict):
        if not isinstance(traducao, list) or len(traducao) != len(base):
            sys.exit(f"{caminho}: a tradução precisa ter {len(base)} itens, como o português")
        return [mesclar(b, t, f"{caminho}[{i}]") for i, (b, t) in enumerate(zip(base, traducao))]
    return traducao


# Campos que não são texto de leitura (endereço, arquivo, identificador, nome próprio): não se traduzem.
CAMPOS_SEM_TEXTO = {"slug", "dados", "capa", "src", "id", "icone", "email", "linkedin", "github", "cv",
                    "heroi_imagem", "foto", "print", "repositorio", "href", "arquivo", "endereco"}
CAMINHOS_SEM_TEXTO = {"nome", "nome_curto", "painel.nome", "experiencia.empresa"}


def textos_sem_traducao(base, traducao, caminho=""):
    """Caminhos dos textos do português que o arquivo em inglês não traduz."""
    faltam = []
    if isinstance(base, dict):
        for k, v in base.items():
            sub = f"{caminho}.{k}" if caminho else k
            if k in CAMPOS_SEM_TEXTO or sub in CAMINHOS_SEM_TEXTO:
                continue
            if not isinstance(traducao, dict) or k not in traducao:
                if tem_texto(v):
                    faltam.append(sub)
            else:
                faltam += textos_sem_traducao(v, traducao[k], sub)
    elif isinstance(base, list) and base and isinstance(base[0], dict):
        for i, b in enumerate(base):
            t = traducao[i] if isinstance(traducao, list) and i < len(traducao) else {}
            faltam += textos_sem_traducao(b, t, f"{caminho}[{i}]")
    return faltam


def tem_texto(valor):
    if isinstance(valor, str):
        return bool(valor.strip())
    if isinstance(valor, list):
        return any(tem_texto(v) for v in valor)
    if isinstance(valor, dict):
        return any(tem_texto(v) for k, v in valor.items() if k not in CAMPOS_SEM_TEXTO)
    return False


def carregar_arquivo(caminho, lingua):
    base = carregar_toml(caminho)
    if lingua == "pt":
        return base
    traduzido = CONTEUDO_EN / caminho.name
    if not traduzido.exists():
        sys.exit(f"Falta a tradução {traduzido.relative_to(RAIZ)}")
    return mesclar(base, carregar_toml(traduzido), traduzido.relative_to(RAIZ).as_posix())


def arquivos_de_projeto():
    return [p for p in sorted(CONTEUDO.glob("*.toml")) if p.stem not in ("perfil", "interface")]


def carregar_perfil(lingua="pt"):
    return carregar_arquivo(CONTEUDO / "perfil.toml", lingua)


def carregar_projetos(lingua="pt"):
    projetos = [carregar_arquivo(p, lingua) for p in arquivos_de_projeto()]
    return sorted(projetos, key=lambda p: p["ordem"])


def carregar_interface(lingua):
    """Textos fixos dos templates (menu, rótulos, botões), um bloco por idioma em conteudo/interface.toml."""
    textos = carregar_toml(CONTEUDO / "interface.toml")
    faltam = sorted(set(textos["pt"]) ^ set(textos[lingua]))
    if faltam:
        sys.exit(f"conteudo/interface.toml: [pt] e [{lingua}] precisam das mesmas chaves ({', '.join(faltam)})")
    return textos[lingua]


def traducoes_pendentes():
    """Textos em português ainda sem versão em inglês, para o verificar listar."""
    faltam = []
    for arq in [CONTEUDO / "perfil.toml", *arquivos_de_projeto()]:
        traduzido = CONTEUDO_EN / arq.name
        if not traduzido.exists():
            faltam.append(f"{traduzido.relative_to(RAIZ)} não existe")
            continue
        faltam += [f"{traduzido.relative_to(RAIZ)}: {c}" for c in
                   textos_sem_traducao(carregar_toml(arq), carregar_toml(traduzido))]
    return faltam


# ---------------------------------------------------------------- gráficos

def decimal_local(x):
    """Uma casa decimal, com vírgula em português e ponto em inglês."""
    texto = f"{x:.1f}"
    return texto.replace(".", ",") if eh_pt() else texto


def percentual_local(x):
    return decimal_local(x) + "%"


# mês da data ISO para o rótulo curto do mês nos dados
MES_DO_NUMERO = {"06": "jun", "07": "jul", "08": "ago", "09": "set", "10": "out", "11": "nov"}


def data_curta(iso):
    """'2026-09-05' vira '05/09' em português e 'Sep 5' em inglês."""
    dia, mes = iso[8:], iso[5:7]
    return f"{dia}/{mes}" if eh_pt() else f"{tr(MES_DO_NUMERO[mes])} {int(dia)}"


def layout_base(**extra):
    base = dict(
        template="none",
        # decimal e milhar, na ordem que o Plotly pede
        separators=",." if eh_pt() else ".,",
        font=dict(family="Inter, system-ui, sans-serif", size=14, color=TINTA),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=24, t=8, b=36),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=GRADE, font=dict(color=TINTA)),
        showlegend=False,
    )
    return {**base, **extra}


def sinal_local(x):
    return ("+" if x > 0 else "") + percentual_local(x)


def nome_loja(loja):
    nome = tr(loja["loja"])
    return f"{nome} ({tr(loja['segmento'])})" if loja.get("segmento") else nome


def eixos_discretos(fig, **extra):
    fig.update_xaxes(showgrid=False, zeroline=False, automargin=True, tickfont=dict(color=TINTA_SECUNDARIA), **extra)
    fig.update_yaxes(showgrid=True, gridcolor=GRADE, zeroline=False, automargin=True,
                     tickfont=dict(color=TINTA_SECUNDARIA))


def seletor(nome, opcoes, visiveis_por_opcao, ativo=0):
    """Opções do seletor HTML que o graficos.js põe acima do gráfico.

    opcoes: lista de (grupo, rótulo); grupo vira <optgroup> quando não é None.
    Cada opção liga só os traços dela.
    """
    return {"seletor": {"nome": nome, "ativo": ativo, "opcoes": [
        {"grupo": g, "rotulo": r, "visivel": v} for (g, r), v in zip(opcoes, visiveis_por_opcao)]}}


def grafico_evolucao(dados, estreito=False):
    """Um painel por loja, mesmo eixo: faturamento e pedidos em índice (primeiro mês = 100)."""
    lojas = dados["lojas"]
    colunas = 1 if estreito else 2
    linhas = -(-len(lojas) // colunas)
    fig = make_subplots(rows=linhas, cols=colunas, shared_yaxes=True, vertical_spacing=0.04 if estreito else 0.09, horizontal_spacing=0.06,
                        subplot_titles=[nome_loja(l) for l in lojas])
    meses = [tr(m) for m in ("jun", "jul", "ago", "set", "out")]
    tabela = []
    for i, loja in enumerate(lojas):
        lin, col = i // colunas + 1, i % colunas + 1
        x = [tr(m["mes"]) for m in loja["meses"]]
        for medida, cor, traco in (("faturamento", COR_DESTAQUE, "solid"), ("pedidos", COR_PAR, "dot")):
            y = [m["indice"][medida] for m in loja["meses"]]
            rotulo = tr(medida.capitalize())
            fig.add_trace(go.Scatter(
                x=x, y=y, mode="lines+markers", name=rotulo, legendgroup=medida, showlegend=i == 0,
                line=dict(color=cor, width=2, dash=traco), marker=dict(size=8, color=cor, line=dict(color="#ffffff", width=2)),
                hovertemplate=f"{tr(loja['loja'])} · %{{x}}<br>{rotulo}: %{{y:.1f}}<extra></extra>",
            ), row=lin, col=col)
        fig.add_hline(y=100, line=dict(color=TINTA_SECUNDARIA, width=1, dash="dash"), opacity=0.5, row=lin, col=col)
        fim = loja["meses"][-1]
        tabela.append((tr("{loja}, {ini} a {fim}").format(loja=tr(loja["loja"]), ini=x[0], fim=x[-1]),
                       tr("faturamento {fat}, pedidos {ped}").format(fat=decimal_local(fim["indice"]["faturamento"]),
                                                                     ped=decimal_local(fim["indice"]["pedidos"]))))
    fig.update_layout(**layout_base(height=(150 if estreito else 170) * linhas + 80, margin=dict(l=40, r=16, t=72, b=24)))
    fig.update_layout(showlegend=True, legend=dict(orientation="h", x=0, y=1, yanchor="top", yref="container",
                                                   font=dict(color=TINTA_SECUNDARIA)))
    fig.update_annotations(font=dict(size=13, color=TINTA))
    fig.update_xaxes(categoryorder="array", categoryarray=meses, range=[-0.4, 4.4], showgrid=False,
                     tickfont=dict(color=TINTA_SECUNDARIA, size=12))
    fig.update_yaxes(showgrid=True, gridcolor=GRADE, zeroline=False, tickfont=dict(color=TINTA_SECUNDARIA, size=12),
                     range=[40, 240], dtick=50, automargin=True, showticklabels=True)
    return fig, tabela


def grafico_funil_lojas(dados):
    """Etapas do funil em % das visitas, uma opção por loja e mês."""
    opcoes = [(loja, m) for loja in dados["lojas"] for m in loja["meses"]]
    fig = go.Figure()
    ativo = next(i for i, (l, m) in enumerate(opcoes) if l["loja"] == "Loja B" and m["mes"] == "set")
    for i, (loja, m) in enumerate(opcoes):
        nomes = [tr(e["etapa"]) for e in m["funil"]]
        valores = [e["pct"] for e in m["funil"]]
        fig.add_trace(go.Bar(
            x=valores, y=nomes, orientation="h", visible=i == ativo,
            marker=dict(color=[COR_SERIE] * (len(valores) - 1) + [COR_DESTAQUE], cornerradius=4),
            text=[percentual_local(v) for v in valores], textposition="outside", textfont=dict(color=TINTA), cliponaxis=False,
            hovertemplate=f"{tr(loja['loja'])} · {tr(m['mes'])}<br>%{{y}}: %{{x:.1f}}% {tr('das visitas')}<extra></extra>",
        ))
    rotulos = [f"{tr(l['loja'])} · {tr(m['mes'])}" for l, m in opcoes]
    fig.update_layout(**layout_base(height=260, bargap=0.4, margin=dict(l=8, r=24, t=8, b=36),
                                    meta=seletor(tr("Loja e mês"), [(nome_loja(l), r) for (l, m), r in zip(opcoes, rotulos)],
                                                 [[j == i for j in range(len(opcoes))] for i in range(len(opcoes))], ativo)))
    fig.update_yaxes(autorange="reversed", automargin=True, tickfont=dict(color=TINTA_SECUNDARIA), ticksuffix="  ")
    fig.update_xaxes(showgrid=True, gridcolor=GRADE, zeroline=False, automargin=True, range=[0, 118], ticksuffix="%",
                     tickfont=dict(color=TINTA_SECUNDARIA))
    tabela = [(r, tr("{pct} das visitas viraram pedido").format(pct=percentual_local(m["funil"][-1]["pct"])))
              for r, (l, m) in zip(rotulos, opcoes)]
    return fig, tabela


def grafico_variacao(dados):
    """Lojas nas linhas, meses nas colunas, uma opção por medida."""
    medidas = [("faturamento", tr("Faturamento"), "%"), ("pedidos", tr("Pedidos"), "%"),
               ("ticket", tr("Ticket médio"), "%"), ("conversao_pp", tr("Conversão"), tr(" p.p."))]
    meses = ["jul", "ago", "set", "out"]
    lojas = dados["lojas"]
    fig = go.Figure()
    for i, (chave, rotulo, sufixo) in enumerate(medidas):
        z, texto = [], []
        for loja in lojas:
            por_mes = {m["mes"]: m["variacao"][chave] for m in loja["meses"] if "variacao" in m}
            z.append([por_mes.get(mes) for mes in meses])
            texto.append([(("+" if v > 0 else "") + decimal_local(v) + sufixo) if v is not None else ""
                          for v in z[-1]])
        limite = 10 if chave == "conversao_pp" else 40
        fig.add_trace(go.Heatmap(
            z=z, x=[tr(m) for m in meses], y=[tr(l["loja"]) for l in lojas], text=texto, texttemplate="%{text}",
            visible=i == 0, textfont=dict(color=TINTA, size=13), colorscale=DIVERGENTE, zmid=0, zmin=-limite, zmax=limite,
            showscale=False, xgap=2, ygap=2, hoverongaps=False,
            hovertemplate=f"%{{y}} · %{{x}} {tr('contra o mês anterior')}<br>{rotulo}: %{{text}}<extra></extra>",
        ))
    fig.update_layout(**layout_base(height=380, margin=dict(l=8, r=8, t=8, b=36),
                                    meta=seletor(tr("Medida"), [(None, m[1]) for m in medidas],
                                                 [[j == i for j in range(len(medidas))] for i in range(len(medidas))])))
    fig.update_yaxes(autorange="reversed", automargin=True, showgrid=False, ticks="", tickfont=dict(color=TINTA_SECUNDARIA),
                     ticksuffix="  ")
    fig.update_xaxes(automargin=True, showgrid=False, tickfont=dict(color=TINTA_SECUNDARIA))
    tabela = [(f"{tr(l['loja'])} · {tr(m['mes'])}",
               tr("faturamento {fat}, pedidos {ped}").format(fat=sinal_local(m["variacao"]["faturamento"]),
                                                             ped=sinal_local(m["variacao"]["pedidos"])))
              for l in lojas for m in l["meses"] if "variacao" in m]
    return fig, tabela


def grafico_caso_loja_b(dados, estreito=False):
    """Pedidos por dia aberto em índice; a janela depois da reordenação de 05/09 em destaque."""
    caso = dados["caso_loja_b"]
    pontos = caso["pontos"]
    janela = ("2026-09-05", "2026-09-13")
    dias = [p["dia"] for p in pontos]
    fig = go.Figure(go.Bar(
        x=dias, y=[p["indice"] for p in pontos],
        marker=dict(color=[COR_DESTAQUE if janela[0] <= d <= janela[1] else COR_SERIE for d in dias], cornerradius=3),
        customdata=[f"{data_curta(p['dia'])} ({tr(p['dia_semana'])})" for p in pontos],
        hovertemplate=f"%{{customdata}}<br>{tr('índice')} %{{y:.0f}}<extra></extra>",
    ))
    fig.add_hline(y=100, line=dict(color=TINTA_SECUNDARIA, width=1, dash="dash"), opacity=0.6,
                  annotation_text=tr("ago = 100") if estreito else tr("média de ago = 100"), annotation_position="right",
                  annotation_font=dict(color=TINTA_SECUNDARIA, size=12))
    for e in caso["eventos"]:
        fig.add_vline(x=e["dia"], line=dict(color=TINTA, width=1.5))
        rotulo = data_curta(e["dia"]) if estreito else tr(e["rotulo"])
        fig.add_annotation(x=e["dia"], y=1, yref="paper", text=rotulo, showarrow=False, xanchor="left", xshift=4,
                           yanchor="top", font=dict(color=TINTA, size=12), bgcolor="rgba(255,255,255,.85)")
    # margem de cima para a barra de ferramentas do Plotly (sempre visível em tela de toque) não cobrir os rótulos,
    # e folga acima da barra mais alta para o rótulo dos eventos não ficar em cima dela
    fig.update_layout(**layout_base(height=330, bargap=0.25, margin=dict(l=8, r=64 if estreito else 120, t=40, b=36)))
    eixos_discretos(fig, type="date", tickformat="%d/%m" if eh_pt() else "%b %-d",
                    dtick=(14 if estreito else 7) * 86400000, tick0="2026-08-03", tickangle=0)
    maior = max(p["indice"] for p in pontos if p["indice"] is not None)
    fig.update_yaxes(title=dict(text=tr("pedidos por dia, índice"), font=dict(color=TINTA_SECUNDARIA, size=12)),
                     range=[0, maior * 1.18])

    def media(a, b):
        v = [p["indice"] for p in pontos if a <= p["dia"] <= b and p["indice"] is not None]
        return sum(v) / len(v)
    tabela = [(tr("01 a 05/08"), decimal_local(media('2026-08-01', '2026-08-05'))),
              (tr("06/08 a 04/09"), decimal_local(media('2026-08-06', '2026-09-04'))),
              (tr("05 a 13/09, depois da reordenação"), decimal_local(media(*janela))),
              (tr("15 a 30/09"), decimal_local(media('2026-09-15', '2026-09-30')))]
    return fig, tabela


def grafico_a_contra_b(dados):
    """Faturamento e pedidos de set contra ago nas duas lojas da mesma cozinha."""
    lojas = [("Loja A", "com anúncio"), ("Loja B", "sem anúncio")]
    por_loja = {l["loja"]: next(m for m in l["meses"] if m["mes"] == "set")["variacao"]
                for l in dados["lojas"] if l["loja"] in dict(lojas)}
    fig = go.Figure()
    for medida, cor in (("faturamento", COR_DESTAQUE), ("pedidos", COR_PAR)):
        valores = [por_loja[l][medida] for l, _ in lojas]
        rotulo = tr(medida.capitalize())
        fig.add_trace(go.Bar(
            x=[f"{tr(l)}<br>{tr(c)}" for l, c in lojas], y=valores, name=rotulo,
            marker=dict(color=cor, cornerradius=4), text=[sinal_local(v) for v in valores], textposition="outside",
            textfont=dict(color=TINTA), cliponaxis=False,
            hovertemplate=f"%{{x}}<br>{rotulo}: %{{text}} {tr('em set contra ago')}<extra></extra>",
        ))
    fig.update_layout(**layout_base(height=300, barmode="group", bargap=0.35, bargroupgap=0.12,
                                    margin=dict(l=8, r=16, t=40, b=36)))
    fig.update_layout(showlegend=True, legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom",
                                                   font=dict(color=TINTA_SECUNDARIA)))
    eixos_discretos(fig)
    fig.update_yaxes(ticksuffix="%", range=[0, 85])
    tabela = [(f"{tr(l)}, {tr(c)}",
               tr("faturamento {fat}, pedidos {ped}").format(fat=sinal_local(por_loja[l]["faturamento"]),
                                                             ped=sinal_local(por_loja[l]["pedidos"])))
              for l, c in lojas]
    return fig, tabela


def grafico_semana_pagamento(dados, estreito=False):
    """Participação por dia da semana e por forma de pagamento no último mês de cada loja."""
    lojas = dados["lojas"]
    fig = make_subplots(rows=2, cols=1, vertical_spacing=0.2,
                        subplot_titles=[tr("Por dia da semana"), tr("Por forma de pagamento")] if estreito
                        else [tr("Pedidos por dia da semana"), tr("Pedidos por forma de pagamento")])
    ordem_pag = ["Pix", "Crédito", "Débito", "Carteira digital", "Vale-refeição", "Dinheiro", "Outros"]
    ativo = next(i for i, l in enumerate(lojas) if l["loja"] == "Loja B")
    visiveis = []
    for i, loja in enumerate(lojas):
        m = loja["meses"][-1]
        dias = list(m["dias"])
        rotulo = f"{tr(loja['loja'])} · {tr(m['mes'])}"
        fig.add_trace(go.Bar(x=[tr(d) for d in dias], y=[m["dias"][d] for d in dias], visible=i == ativo,
                             marker=dict(color=COR_SERIE, cornerradius=3),
                             text=[f"{m['dias'][d]:.0f}%" if estreito else percentual_local(m["dias"][d]) for d in dias],
                             textposition="outside", textangle=0, textfont=dict(color=TINTA, size=11 if estreito else 12),
                             cliponaxis=False,
                             hovertemplate=f"{rotulo}<br>%{{x}}: %{{y:.1f}}%<extra></extra>"), row=1, col=1)
        pag = [p for p in ordem_pag if m["pagamento"].get(p)]
        fig.add_trace(go.Bar(x=[m["pagamento"][p] for p in pag], y=[tr(p) for p in pag], orientation="h",
                             visible=i == ativo, marker=dict(color=COR_SERIE, cornerradius=3),
                             text=[percentual_local(m["pagamento"][p]) for p in pag],
                             textposition="outside", textfont=dict(color=TINTA, size=12), cliponaxis=False,
                             hovertemplate=f"{rotulo}<br>%{{y}}: %{{x:.1f}}%<extra></extra>"), row=2, col=1)
        visiveis.append([j // 2 == i for j in range(2 * len(lojas))])
    rotulos = [f"{tr(l['loja'])} · {tr(l['meses'][-1]['mes'])}" for l in lojas]
    fig.update_layout(**layout_base(height=560, bargap=0.3, margin=dict(l=8, r=24, t=40, b=24),
                                    meta=seletor(tr("Loja"), [(None, f"{nome_loja(l)} · {tr(l['meses'][-1]['mes'])}")
                                                              for l in lojas],
                                                 visiveis, ativo)))
    fig.update_annotations(font=dict(size=13, color=TINTA), xanchor="left", x=0)
    fig.update_xaxes(showgrid=False, tickangle=0, tickfont=dict(color=TINTA_SECUNDARIA, size=11 if estreito else 14),
                     row=1, col=1)
    fig.update_yaxes(showgrid=True, gridcolor=GRADE, ticksuffix="%", range=[0, 40], tickfont=dict(color=TINTA_SECUNDARIA), row=1, col=1)
    fig.update_xaxes(showgrid=True, gridcolor=GRADE, ticksuffix="%", range=[0, 65], tickfont=dict(color=TINTA_SECUNDARIA), row=2, col=1)
    fig.update_yaxes(autorange="reversed", automargin=True, ticksuffix="  ", tickfont=dict(color=TINTA_SECUNDARIA), row=2, col=1)
    tabela = []
    for r, l in zip(rotulos, lojas):
        m = l["meses"][-1]
        dia = max(m["dias"], key=m["dias"].get)
        tabela.append((r, tr("dia mais forte {dia} ({pct}), Pix {pix}").format(
            dia=tr(dia), pct=percentual_local(m["dias"][dia]), pix=percentual_local(m["pagamento"].get("Pix", 0)))))
    return fig, tabela


def efeitos_faturamento(variacao):
    """Quebra a variação do faturamento (em pontos, mês anterior = 100) em efeito de pedidos e de ticket.

    Faturamento = pedidos x ticket. Cada efeito usa a média do outro fator nos dois meses, então a ordem
    não favorece nenhum dos dois e a soma dá exatamente a variação. Mesma conta de consultas/02-cascata.sql.
    """
    vp, vt = variacao["pedidos"] / 100, variacao["ticket"] / 100
    return 100 * vp * (2 + vt) / 2, 100 * vt * (2 + vp) / 2


def grafico_cascata(dados):
    """Cascata do faturamento: mês anterior = 100, mais o efeito dos pedidos e do ticket, igual ao mês."""
    opcoes = [(loja, m, ant) for loja in dados["lojas"]
              for ant, m in zip(loja["meses"], loja["meses"][1:])]
    ativo = next(i for i, (l, m, _) in enumerate(opcoes) if l["loja"] == "Loja B" and m["mes"] == "set")
    fig = go.Figure()
    tabela = []
    rotulos = [tr("{loja} · {mes} contra {ant}").format(loja=tr(l["loja"]), mes=tr(m["mes"]), ant=tr(a["mes"]))
               for l, m, a in opcoes]
    for i, ((loja, m, ant), rotulo) in enumerate(zip(opcoes, rotulos)):
        ped, tic = efeitos_faturamento(m["variacao"])
        final = 100 + ped + tic
        fig.add_trace(go.Waterfall(
            x=[f"{tr(ant['mes'])} = 100", tr("pedidos"), tr("ticket médio"), tr(m["mes"])],
            measure=["absolute", "relative", "relative", "total"], y=[100, ped, tic, 0],
            base=0, visible=i == ativo, connector=dict(line=dict(color=GRADE, width=1)),
            increasing=dict(marker=dict(color=COR_DESTAQUE)), decreasing=dict(marker=dict(color=COR_PAR)),
            totals=dict(marker=dict(color=COR_SERIE)),
            text=["100", sinal_local(ped).replace("%", ""), sinal_local(tic).replace("%", ""), decimal_local(final)],
            textposition="outside", textfont=dict(color=TINTA), cliponaxis=False,
            hovertemplate=f"{rotulo}<br>%{{x}}: %{{text}}<extra></extra>",
        ))
        tabela.append((rotulo, tr("pedidos {ped}, ticket {tic}, faturamento {fat}").format(
            ped=sinal_local(ped)[:-1], tic=sinal_local(tic)[:-1], fat=decimal_local(final))))
    fig.update_layout(**layout_base(height=320, bargap=0.35, waterfallgap=0.35, margin=dict(l=8, r=16, t=24, b=36),
                                    meta=seletor(tr("Loja e mês"), [(nome_loja(l), r) for (l, _, _), r in zip(opcoes, rotulos)],
                                                 [[j == i for j in range(len(opcoes))] for i in range(len(opcoes))], ativo)))
    eixos_discretos(fig)
    # eixo começa abaixo de 100 para o degrau aparecer; o mês anterior é sempre 100
    menor = min(min(100, 100 + efeitos_faturamento(m["variacao"])[0]) + min(0, efeitos_faturamento(m["variacao"])[1])
                for _, m, _ in opcoes)
    maior = max(100 + sum(max(0, e) for e in efeitos_faturamento(m["variacao"])) for _, m, _ in opcoes)
    fig.update_yaxes(range=[max(0, menor - 15), maior + 15],
                     title=dict(text=tr("faturamento, índice"), font=dict(color=TINTA_SECUNDARIA, size=12)))
    return fig, tabela


def grafico_abc(dados):
    """Curva ABC: % do cardápio (do item que mais vende ao que não vende) contra % acumulado da receita."""
    lojas = dados["lojas"]
    ativo = next(i for i, l in enumerate(lojas) if l["loja"] == "Loja B")
    fig = go.Figure()
    tabela, visiveis = [], []
    for i, loja in enumerate(lojas):
        n = loja["itens_no_cardapio"]
        acum, xs, ys, nomes = 0.0, [0.0], [0.0], [""]
        k80 = None
        for k, item in enumerate(loja["itens"], 1):
            acum += item["pct"]
            xs.append(100 * k / n)
            ys.append(min(acum, 100.0))
            nomes.append(tr(item["item"]))
            if k80 is None and acum >= 80:
                k80 = k
        sem_venda = n - len(loja["itens"])
        if sem_venda:
            xs.append(100.0)
            ys.append(100.0)
            nomes.append(tr("{n} itens sem venda").format(n=sem_venda))
        x80 = 100 * k80 / n
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", visible=i == ativo, line=dict(color=COR_DESTAQUE, width=2, shape="linear"),
            fill="tozeroy", fillcolor="rgba(29,78,216,.08)", customdata=nomes,
            hovertemplate=f"%{{x:.0f}}% {tr('do cardápio')} · %{{y:.1f}}% {tr('da receita')}<br>%{{customdata}}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=[x80], y=[ys[k80]], mode="markers+text", visible=i == ativo,
            marker=dict(size=10, color=COR_DESTAQUE, line=dict(color="#ffffff", width=2)),
            text=[tr("{k} de {n} itens ({pct}%)<br>fazem 80% da receita").format(k=k80, n=n, pct=f"{x80:.0f}")],
            textposition="bottom right", textfont=dict(color=TINTA, size=12), cliponaxis=False, hoverinfo="skip",
        ))
        visiveis.append([j // 2 == i for j in range(2 * len(lojas))])
        tabela.append((f"{tr(loja['loja'])} · {tr(dados['mes'])}",
                       tr("{k} de {n} itens ({pct}% do cardápio) fazem 80% da receita; {s} sem venda").format(
                           k=k80, n=n, pct=f"{x80:.0f}", s=sem_venda)))
    fig.add_hline(y=80, line=dict(color=TINTA_SECUNDARIA, width=1, dash="dash"), opacity=0.6)
    # sem barra de ferramentas: no canto de cima ela cobria o fim da curva em 100%
    fig.update_layout(**layout_base(height=320, margin=dict(l=8, r=16, t=16, b=40),
                                    meta={**seletor(tr("Loja"), [(None, f"{tr(l['loja'])} · {tr(dados['mes'])}")
                                                                 for l in lojas], visiveis, ativo), "sem_barra": True}))
    eixos_discretos(fig)
    # os dois 0% se encontram no canto de baixo: afasta os rótulos de cada eixo
    fig.update_xaxes(range=[0, 100], ticksuffix="%", dtick=20, ticklabelstandoff=8,
                     title=dict(text=tr("itens do cardápio, do que mais vende ao sem venda"),
                                font=dict(color=TINTA_SECUNDARIA, size=12)))
    fig.update_yaxes(range=[0, 104], ticksuffix="%", dtick=20, ticklabelstandoff=10,
                     title=dict(text=tr("receita acumulada"), font=dict(color=TINTA_SECUNDARIA, size=12)))
    return fig, tabela


GRAFICOS = {
    "cascata": grafico_cascata,
    "abc": grafico_abc,
    "evolucao": grafico_evolucao,
    "funil": grafico_funil_lojas,
    "variacao": grafico_variacao,
    "caso-loja-b": grafico_caso_loja_b,
    "a-contra-b": grafico_a_contra_b,
    "semana-pagamento": grafico_semana_pagamento,
}


def montar_graficos(projeto):
    """Devolve a lista de gráficos do projeto, prontos ou pendentes."""
    saida = []
    for g in projeto.get("graficos", []):
        item = dict(g)
        if "pendente" not in g:
            dados = json.loads((DADOS / g["dados"]).read_text(encoding="utf-8"))
            funcao = GRAFICOS[g["id"]]
            fig, tabela = funcao(dados)
            # "</" escapado para o JSON não fechar a tag <script> antes da hora.
            item["figura"] = fig.to_json().replace("</", "<\\/")
            item["tabela"] = tabela
            # em tela estreita o graficos.js troca pela versão de uma coluna, quando o gráfico tem uma
            if "estreito" in inspect.signature(funcao).parameters:
                item["figura_estreita"] = funcao(dados, estreito=True)[0].to_json().replace("</", "<\\/")
        saida.append(item)
    return saida


# ---------------------------------------------------------------- consultas SQL

def banco_consultas():
    """SQLite em memória com as tabelas que as consultas da página /consultas-sql/ leem.

    Vem dos mesmos JSON anonimizados dos gráficos. Os índices de venda são encadeados pela variação
    mês cheio contra mês cheio (primeiro mês = 100), então o LAG devolve a mesma variação dos gráficos.
    """
    lojas = json.loads((DADOS / "lojas.json").read_text(encoding="utf-8"))
    itens = json.loads((DADOS / "itens.json").read_text(encoding="utf-8"))
    banco = sqlite3.connect(":memory:")
    banco.executescript("""
        CREATE TABLE lojas (loja TEXT PRIMARY KEY, segmento TEXT);
        CREATE TABLE vendas_mes (loja TEXT REFERENCES lojas, mes_num INTEGER, mes TEXT,
                                 idx_faturamento REAL, idx_pedidos REAL, idx_ticket REAL,
                                 PRIMARY KEY (loja, mes_num));
        CREATE TABLE pedidos_dia (loja TEXT, dia TEXT, indice REAL, PRIMARY KEY (loja, dia));
        CREATE TABLE cardapio (loja TEXT PRIMARY KEY, itens_no_cardapio INTEGER);
        CREATE TABLE itens_mes (loja TEXT REFERENCES cardapio, linha INTEGER, item TEXT, pct REAL,
                                PRIMARY KEY (loja, linha));
    """)
    ordem = {"jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10}
    for loja in lojas["lojas"]:
        banco.execute("INSERT INTO lojas VALUES (?, ?)", (loja["loja"], loja.get("segmento")))
        idx = {"faturamento": 100.0, "pedidos": 100.0, "ticket": 100.0}
        for m in loja["meses"]:
            if "variacao" in m:
                idx = {k: v * (1 + m["variacao"][k] / 100) for k, v in idx.items()}
            banco.execute("INSERT INTO vendas_mes VALUES (?, ?, ?, ?, ?, ?)",
                          (loja["loja"], ordem[m["mes"]], m["mes"], idx["faturamento"], idx["pedidos"], idx["ticket"]))
    caso = lojas["caso_loja_b"]
    banco.executemany("INSERT INTO pedidos_dia VALUES (?, ?, ?)",
                      [(caso["loja"], p["dia"], p["indice"]) for p in caso["pontos"]])
    for loja in itens["lojas"]:
        banco.execute("INSERT INTO cardapio VALUES (?, ?)", (loja["loja"], loja["itens_no_cardapio"]))
        # chave pela linha do cardápio: o painel tem itens diferentes com o mesmo nome anonimizado
        banco.executemany("INSERT INTO itens_mes VALUES (?, ?, ?, ?)",
                          [(loja["loja"], n, i["item"], i["pct"]) for n, i in enumerate(loja["itens"], 1)])
    return banco


PALAVRAS_SQL = {
    "select", "from", "where", "join", "on", "as", "and", "or", "not", "in", "is", "null", "group", "by",
    "order", "with", "over", "partition", "window", "rows", "unbounded", "preceding", "case", "when", "then",
    "else", "end", "between", "desc", "asc", "filter", "left", "inner", "having", "limit", "distinct",
}
FUNCOES_SQL = {"lag", "lead", "sum", "count", "avg", "round", "min", "max", "row_number", "rank"}
TOKEN_SQL = re.compile(r"(?P<com>--[^\n]*)|(?P<str>'[^']*')|(?P<num>\b\d+(?:\.\d+)?\b)|(?P<pal>\b[A-Za-z_]\w*\b)")


def destacar_sql(texto):
    """HTML do SQL com uma classe por tipo de palavra, para a cor de sintaxe vir do CSS."""
    saida, pos = [], 0
    for t in TOKEN_SQL.finditer(texto):
        saida.append(escape(texto[pos:t.start()]))
        valor, tipo = t.group(), t.lastgroup
        if tipo == "pal":
            tipo = "kw" if valor.lower() in PALAVRAS_SQL else "fn" if valor.lower() in FUNCOES_SQL else None
        saida.append(f'<span class="sql-{tipo}">{escape(valor)}</span>' if tipo else escape(valor))
        pos = t.end()
    saida.append(escape(texto[pos:]))
    return Markup("".join(saida))


def celula_br(valor):
    if valor is None:
        return "-"
    if isinstance(valor, float):
        return decimal_local(valor) if valor != int(valor) or abs(valor) < 1000 else str(int(valor))
    return str(valor)


def montar_consultas():
    config = carregar_toml(CONSULTAS / "consultas.toml")
    banco = banco_consultas()
    for b in config["blocos"]:
        sql = (CONSULTAS / b["arquivo"]).read_text(encoding="utf-8")
        cursor = banco.execute(sql)
        b["sql_html"] = destacar_sql(sql.strip())
        b["colunas"] = [c[0] for c in cursor.description]
        b["linhas"] = [[celula_br(v) for v in linha] for linha in cursor.fetchall()]
    return config


# ---------------------------------------------------------------- build

def ambiente():
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True,
                      undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    env.globals["versao_favicon"] = versao_favicon()
    env.filters["versionado"] = versionado
    return env


def versionado(endereco):
    """'/static/...' com ?v= do hash do arquivo: o Cloudflare deixa o navegador guardar CSS e JS por horas,
    e sem isso quem já visitou o site recebe o HTML novo com o CSS antigo."""
    arq = STATIC / endereco.removeprefix("/static/")
    return f"{endereco}?v={hashlib.sha256(arq.read_bytes()).hexdigest()[:10]}"


def versao_favicon():
    """Hash curto dos arquivos do favicon, que vai como ?v= nos links: o arquivo novo tem o mesmo nome,
    e sem isso o navegador de quem já visitou o site segue mostrando o favicon antigo do cache."""
    h = hashlib.sha256()
    for arq in sorted((STATIC / "favicon").glob("*.*")):
        h.update(arq.name.encode() + arq.read_bytes())
    return h.hexdigest()[:10]


def escrever(caminho, texto):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")


# ---------------------------------------------------------------- painéis

PLOTLY_LOCAL = '<script src="/static/vendor/plotly.min.js"></script>'
# Bloco do plotly.js embutido pelo gerador do painel: do cabeçalho de licença até o </script>.
PLOTLY_EMBUTIDO = re.compile(r"<script>/\*\*\s*\* plotly\.js (v[\d.]+)\n.*?</script>", re.S)
VERSAO_PLOTLY = re.compile(r"plotly\.js (v[\d.]+)")

BARRA_VOLTAR = (
    '<nav style="font:14px/1.4 system-ui,sans-serif;padding:10px 16px;background:#111418;">'
    '<a href="/projetos/{slug}/" style="color:#f0efec;text-decoration:none;">'
    '<span aria-hidden="true">←</span> Voltar ao estudo de caso</a></nav>'
)


def importar_painel(origem, nome):
    """Copia um painel HTML já anonimizado, trocando o plotly.js embutido pelo do site.

    O painel chega pronto e anonimizado do projeto de origem; aqui só sai o plotly.js
    (5 MB que o site já serve em /static/vendor) e a cópia passa pela mesma busca de dado sensível.
    """
    html = Path(origem).read_text(encoding="utf-8")
    achado = PLOTLY_EMBUTIDO.search(html)
    if not achado:
        sys.exit("Não achei o plotly.js embutido no painel: o formato mudou, confira antes de importar.")
    versao_site = VERSAO_PLOTLY.search(get_plotlyjs()[:300]).group(1)
    if achado.group(1) != versao_site:
        sys.exit(f"O painel usa plotly.js {achado.group(1)} e o site serve {versao_site}: alinhe as versões antes.")
    html = html[:achado.start()] + PLOTLY_LOCAL + html[achado.end():]

    problemas = [f"{tipo}: '{t}'" for tipo, padrao in PADROES.items() for t in padrao.findall(html)]
    termos = carregar_termos() or []
    normal = normalizar(html)
    problemas += ["termo proibido da lista" for t in termos if t in normal]
    if problemas:
        for linha in problemas:
            print("ERRO:", linha, file=sys.stderr)
        sys.exit("Painel não importado: dado sensível encontrado.")

    destino = PAINEIS / nome / "painel.html"
    escrever(destino, html)
    print(f"Painel gravado em {destino.relative_to(RAIZ)} (plotly.js {versao_site} do site)")


AUTOR_META = re.compile(r'(<meta name="author" content=")[^"]*(")')
AUTOR_RODAPE = re.compile(r'("autor":\s*")[^"]*(")')


def caminho_painel(projeto):
    return f"/projetos/{projeto['slug']}/painel/"


def publicar_painel(projeto, perfil):
    """Grava o painel do projeto em dist/projetos/<slug>/painel/ com a barra de volta ao estudo de caso.

    O gerador do painel assina com o nome curto; no site vale o nome completo do perfil,
    no metadado e no rodapé do painel, igual ao resto das páginas.
    O painel só existe em português (vem pronto do projeto de origem).
    """
    html = (PAINEIS / projeto["painel"]["nome"] / "painel.html").read_text(encoding="utf-8")
    for padrao in (AUTOR_META, AUTOR_RODAPE):
        html, trocas = padrao.subn(lambda m: m.group(1) + perfil["nome"] + m.group(2), html, count=1)
        if not trocas:
            sys.exit(f"Não achei o autor no painel ({padrao.pattern}): o formato mudou, confira antes de publicar.")
    barra = BARRA_VOLTAR.format(slug=projeto["slug"])
    html = html.replace("<body>", "<body>\n" + barra, 1)
    # mesmo favicon das outras páginas e o endereço oficial no domínio
    if "</head>" not in html:
        sys.exit("Não achei o </head> no painel: o formato mudou, confira antes de publicar.")
    canonical = f'  <link rel="canonical" href="{escape(perfil["endereco"] + caminho_painel(projeto))}">\n'
    html = html.replace("</head>", ambiente().get_template("favicon.html").render() + canonical + "</head>", 1)
    escrever(DIST / caminho_painel(projeto).strip("/") / "index.html", html)


def destino_da_pagina(lingua, caminho, arquivo="index.html"):
    return DIST.joinpath(*LINGUAS[lingua]["raiz"].strip("/").split("/"), *caminho.strip("/").split("/"), arquivo)


def gerar_lingua(env, lingua, linguas, tema, config):
    """Gera as páginas de um idioma. Devolve True se alguma página usa o Plotly."""
    perfil = carregar_perfil(lingua)
    projetos = carregar_projetos(lingua)
    for p in projetos:
        p["graficos_montados"] = montar_graficos(p)
    outra = next((l for l in linguas if l != lingua), None)
    comum = dict(perfil=perfil, projetos=projetos, tema=dict(config, nome=tema) if tema else None,
                 layout=config.get("layout", "base.html"), t=carregar_interface(lingua), lingua=lingua,
                 raiz=LINGUAS[lingua]["raiz"], linguas=LINGUAS, outra=outra)

    def pagina(template, nome, caminho, idiomas, arquivo="index.html", **extra):
        # urls: endereço desta página em cada idioma que a tem (canonical e hreflang); None na 404
        urls = {l: LINGUAS[l]["raiz"] + caminho for l in idiomas} if caminho else None
        # o botão de idioma leva à mesma página no outro idioma, ou ao início dele se a página não existir lá
        troca = (urls or {}).get(outra, LINGUAS[outra]["raiz"] + "/") if outra else None
        html = env.get_template(template).render(**comum, pagina=nome, urls=urls, troca=troca, **extra)
        escrever(destino_da_pagina(lingua, caminho or "/", arquivo), html)

    pagina(config.get("index", "index.html"), "inicio", "/", linguas)
    for p in projetos:
        pagina("projeto.html", p["slug"], f"/projetos/{p['slug']}/", linguas, projeto=p)
        if "painel" in p and lingua == "pt":
            publicar_painel(p, perfil)
    # as consultas SQL só existem em português (nomes de coluna e resultados vêm dos dados em português)
    if lingua == "pt":
        pagina("consultas.html", "consultas-sql", "/consultas-sql/", ["pt"], consultas=montar_consultas())
    pagina("404.html", "404", None, linguas, arquivo="404.html")
    return any(any("figura" in g for g in p["graficos_montados"]) or "painel" in p for p in projetos)


def gerar_sitemap(endereco, linguas, projetos):
    """sitemap.xml com cada página em cada idioma e os endereços alternativos, mais o robots.txt."""
    paginas = [("/", linguas)] + [(f"/projetos/{p['slug']}/", linguas) for p in projetos]
    paginas += [(caminho_painel(p), ["pt"]) for p in projetos if "painel" in p]
    paginas.append(("/consultas-sql/", ["pt"]))
    linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for caminho, idiomas in paginas:
        urls = {l: escape(endereco + LINGUAS[l]["raiz"] + caminho) for l in idiomas}
        for l in idiomas:
            linhas.append(f"  <url>\n    <loc>{urls[l]}</loc>")
            if len(idiomas) > 1:
                linhas += [f'    <xhtml:link rel="alternate" hreflang="{LINGUAS[o]["html"]}" href="{urls[o]}"/>'
                           for o in idiomas]
                linhas.append(f'    <xhtml:link rel="alternate" hreflang="x-default" href="{urls["pt"]}"/>')
            linhas.append("  </url>")
    linhas.append("</urlset>")
    escrever(DIST / "sitemap.xml", "\n".join(linhas) + "\n")
    escrever(DIST / "robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {endereco}/sitemap.xml\n")


def build(tema=None):
    perfil = carregar_perfil()
    projetos = carregar_projetos()
    env = ambiente()
    endereco = perfil["endereco"]
    if not re.fullmatch(r"https://[a-z0-9.-]+", endereco):
        sys.exit(f"perfil.toml: endereco precisa ser https://dominio, sem barra no fim (está '{endereco}')")

    if DIST.exists():
        shutil.rmtree(DIST)
    # só o CSS do tema escolhido vai para dist/; no build padrão, nenhum
    css_tema = f"tema-{tema}.css" if tema else None
    # e as opções de favicon não escolhidas (static/favicon/opcoes/) ficam fora do ar
    shutil.copytree(STATIC, DIST / "static", ignore=lambda pasta, nomes: [
        n for n in nomes if (n.startswith("tema-") and n.endswith(".css") and n != css_tema)
        or (n == "opcoes" and Path(pasta).name == "favicon")])
    # o navegador pede /favicon.ico na raiz mesmo sem link (leitor de RSS, aba de PDF, versões antigas)
    shutil.copy2(STATIC / "favicon" / "favicon.ico", DIST / "favicon.ico")

    config = TEMAS[tema] if tema else {}
    # a versão em inglês só sai nos visuais com o botão de idioma (hoje a vitrine, a publicada)
    linguas = list(LINGUAS) if config.get("idiomas") else ["pt"]
    usa_plotly = False
    SEM_TRADUCAO.clear()
    for lingua in linguas:
        with em_lingua(lingua):
            usa_plotly |= gerar_lingua(env, lingua, linguas, tema, config)
    if SEM_TRADUCAO:
        for rotulo in sorted(SEM_TRADUCAO):
            print(f"ERRO: rótulo de gráfico sem tradução em conteudo/en/graficos.toml: '{rotulo}'", file=sys.stderr)
        sys.exit("Build falhou: a versão em inglês sairia com rótulo em português.")
    if usa_plotly:
        escrever(DIST / "static" / "vendor" / "plotly.min.js", get_plotlyjs())
    gerar_sitemap(endereco, linguas, projetos)

    print(f"Site gerado em {DIST}" + (f" (tema {tema})" if tema else "") + f", idiomas: {', '.join(linguas)}")
    for linha in traducoes_pendentes() if len(linguas) > 1 else []:
        print("AVISO: texto sem tradução para o inglês:", linha, file=sys.stderr)
    problemas = verificar_sensiveis(estrito=False)
    if problemas:
        for linha in problemas:
            print("ERRO:", linha, file=sys.stderr)
        sys.exit("Build falhou: dado sensível encontrado. Nada deve ser publicado.")


# ---------------------------------------------------------------- verificar

PADROES = {
    "CPF": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    "CNPJ": re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"),
    "telefone": re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-\d{4}\b"),
    "e-mail": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
}
EXTENSOES_TEXTO = {".html", ".json", ".css", ".js", ".txt", ".toml", ".xml", ".svg", ".sql"}


def normalizar(texto):
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.casefold()


def carregar_termos():
    pasta = os.environ.get(VAR_PRIVADO)
    if not pasta:
        return None
    caminho = Path(pasta) / ARQUIVO_TERMOS
    if not caminho.exists():
        return None
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    return [normalizar(t.strip()) for t in linhas if t.strip() and not t.startswith("#")]


def arquivos_para_verificar():
    for pasta in (DADOS, DIST, CONTEUDO, STATIC, PAINEIS, CONSULTAS):
        if not pasta.exists():
            continue
        for arq in pasta.rglob("*"):
            if arq.is_file() and arq.suffix in EXTENSOES_TEXTO | {".pdf"} and "vendor" not in arq.parts:
                yield arq


def ler_texto(arq):
    """Texto do arquivo; PDF (o CV) passa pelo pypdf. None se não der para ler.

    pypdf e não pdftotext: o build do Cloudflare Pages não tem o poppler e não instala pacote do sistema.
    """
    if arq.suffix != ".pdf":
        return arq.read_text(encoding="utf-8", errors="ignore")
    try:
        return "\n".join(pagina.extract_text() or "" for pagina in PdfReader(arq).pages)
    except PdfReadError:
        return None


def verificar_sensiveis(estrito):
    """Lista os achados. Sem a lista de termos, avisa (build) ou falha (verificar)."""
    problemas = []
    termos = carregar_termos()
    if termos is None:
        aviso = (f"lista de termos proibidos não encontrada (defina {VAR_PRIVADO} "
                 f"apontando para a pasta com {ARQUIVO_TERMOS})")
        if estrito:
            problemas.append(aviso)
        else:
            print("AVISO:", aviso, file=sys.stderr)
        termos = []

    for arq in arquivos_para_verificar():
        texto = ler_texto(arq)
        rel = arq.relative_to(RAIZ)
        if texto is None:
            problemas.append(f"{rel}: não consegui ler o texto do PDF")
            continue
        for nome, padrao in PADROES.items():
            for achado in padrao.findall(texto):
                if nome == "e-mail" and achado.lower() == EMAIL_PERMITIDO:
                    continue
                problemas.append(f"{rel}: {nome} '{achado}'")
        if termos:
            normal = normalizar(texto)
            for termo in termos:
                if termo in normal:
                    problemas.append(f"{rel}: termo proibido da lista")
    return problemas


def listar_pendencias():
    perfil = carregar_perfil()
    pendencias = []
    if not perfil.get("cv"):
        pendencias.append("perfil: CV em PDF ainda não escolhido")
    for p in carregar_projetos():
        if p.get("repositorio_pendente"):
            pendencias.append(f"{p['slug']}: {p['repositorio_pendente']}")
        for g in p.get("graficos", []):
            if "pendente" in g:
                pendencias.append(f"{p['slug']}: gráfico '{g['titulo']}': {g['pendente']}")
    for b in carregar_toml(CONSULTAS / "consultas.toml").get("blocos", []):
        if "mudou_pendente" in b:
            pendencias.append(f"consultas-sql: bloco '{b['id']}': {b['mudou_pendente']}")
    pendencias += [f"inglês: {linha}" for linha in traducoes_pendentes()]
    return pendencias


def verificar():
    problemas = verificar_sensiveis(estrito=True)
    pendencias = listar_pendencias()
    for linha in pendencias:
        print("PENDENTE:", linha)
    for linha in problemas:
        print("ERRO:", linha, file=sys.stderr)
    if problemas:
        sys.exit(1)
    print("Nenhum dado sensível encontrado." + (" Há pendências acima." if pendencias else ""))


# ---------------------------------------------------------------- serve

class Handler(SimpleHTTPRequestHandler):
    def send_error(self, code, message=None, explain=None):
        # como no Cloudflare Pages: vale o 404.html mais perto do endereço pedido (/en/... usa o da versão em inglês)
        ingles = DIST / "en" / "404.html"
        pagina = ingles if self.path.startswith("/en/") and ingles.exists() else DIST / "404.html"
        if code == 404 and pagina.exists():
            corpo = pagina.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        super().send_error(code, message, explain)


def serve(porta, tema=None):
    build(tema)
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), partial(Handler, directory=str(DIST)))
    print(f"Servindo em http://localhost:{porta} (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description="Site do portfólio")
    sub = parser.add_subparsers(dest="comando", required=True)
    build_p = sub.add_parser("build", help="gera dist/")
    serve_p = sub.add_parser("serve", help="gera e serve localmente")
    serve_p.add_argument("--porta", type=int, default=8000)
    for p in (build_p, serve_p):
        p.add_argument("--tema", choices=[*sorted(TEMAS), SEM_TEMA], default=TEMA_PUBLICADO,
                       help=f"variação de visual (padrão: {TEMA_PUBLICADO}, a publicada; {SEM_TEMA}: o visual antigo)")
    sub.add_parser("verificar", help="procura dado sensível e lista pendências")
    imp = sub.add_parser("importar-painel", help="traz um painel HTML já anonimizado para paineis/")
    imp.add_argument("origem", help="arquivo HTML do painel anonimizado")
    imp.add_argument("nome", help="pasta de destino dentro de paineis/")
    args = parser.parse_args()

    tema = None if getattr(args, "tema", None) == SEM_TEMA else getattr(args, "tema", None)
    if args.comando == "build":
        build(tema)
    elif args.comando == "serve":
        serve(args.porta, tema)
    elif args.comando == "importar-painel":
        importar_painel(args.origem, args.nome)
    else:
        verificar()


if __name__ == "__main__":
    main()
