"""Gera, serve e verifica o site do portfólio.

    python site.py build       gera a pasta dist/
    python site.py serve       gera e serve em http://localhost:8000
    python site.py verificar   procura dado sensível em dados/ e dist/ e lista as pendências

O site só lê conteudo/ (texto) e dados/ (JSON já anonimizado e agregado).
"""

import argparse
import inspect
import json
import os
import re
import shutil
import sys
import tomllib
import unicodedata
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from plotly.offline import get_plotlyjs

RAIZ = Path(__file__).resolve().parent
CONTEUDO = RAIZ / "conteudo"
DADOS = RAIZ / "dados"
TEMPLATES = RAIZ / "templates"
STATIC = RAIZ / "static"
DIST = RAIZ / "dist"

# Pasta fora do repositório com o de-para da anonimização e a lista de termos proibidos.
VAR_PRIVADO = "PORTFOLIO_PRIVADO"
ARQUIVO_TERMOS = "termos-proibidos.txt"

EMAIL_PERMITIDO = "bessapedro500@gmail.com"

# Cores do gráfico: barras em cinza e a etapa final no tom de destaque, como os cartões da página inicial.
COR_SERIE = "#9aa1ab"
COR_DESTAQUE = "#4d7c0f"
TINTA = "#111418"
TINTA_SECUNDARIA = "#4a4f57"
GRADE = "#e3e2dc"
# Segunda série quando duas medidas dividem o gráfico (validada contra o destaque, inclusive para daltonismo).
COR_PAR = "#2a78d6"
# Variação: vermelho para queda, azul para alta, cinza no zero.
DIVERGENTE = [[0, "#e34948"], [0.5, "#f0efec"], [1, "#2a78d6"]]


# ---------------------------------------------------------------- conteúdo

def carregar_toml(caminho):
    with open(caminho, "rb") as f:
        return tomllib.load(f)


def carregar_projetos():
    projetos = [carregar_toml(p) for p in sorted(CONTEUDO.glob("*.toml")) if p.stem != "perfil"]
    return sorted(projetos, key=lambda p: p["ordem"])


# ---------------------------------------------------------------- gráficos

def numero_br(n):
    return f"{n:,}".replace(",", ".")


def decimal_br(x):
    return f"{x:.1f}".replace(".", ",")


def percentual_br(x):
    return decimal_br(x) + "%"


def layout_base(**extra):
    base = dict(
        template="none",
        separators=",.",
        font=dict(family="Inter, system-ui, sans-serif", size=14, color=TINTA),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=8, r=24, t=8, b=36),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=GRADE, font=dict(color=TINTA)),
        showlegend=False,
    )
    return {**base, **extra}


def grafico_funil_coleta(dados):
    etapas = dados["funil_coleta"]
    base = etapas[0]["vagas"]
    nomes = [e["etapa"] for e in etapas]
    valores = [e["vagas"] for e in etapas]
    rotulos = [numero_br(v) if i == 0 else f"{numero_br(v)} ({percentual_br(100 * v / base)})"
               for i, v in enumerate(valores)]
    fig = go.Figure(go.Bar(
        x=valores,
        y=nomes,
        orientation="h",
        marker=dict(color=[COR_SERIE] * (len(valores) - 1) + [COR_DESTAQUE], cornerradius=4),
        text=rotulos,
        textposition="outside",
        textfont=dict(color=TINTA),
        cliponaxis=False,
        customdata=[percentual_br(100 * v / base) for v in valores],
        hovertemplate="%{y}<br>%{x:,} vagas (%{customdata} das brutas)<extra></extra>",
    ))
    fig.update_layout(**layout_base(height=240, bargap=0.45))
    fig.update_yaxes(autorange="reversed", automargin=True, tickfont=dict(color=TINTA_SECUNDARIA), ticksuffix="  ")
    fig.update_xaxes(showgrid=True, gridcolor=GRADE, zeroline=False, automargin=True, separatethousands=True,
                     tickfont=dict(color=TINTA_SECUNDARIA), range=[0, base * 1.18])
    tabela = [(n, r) for n, r in zip(nomes, rotulos)]
    return fig, tabela


def sinal_br(x):
    return ("+" if x > 0 else "") + percentual_br(x)


def nome_loja(loja):
    return f"{loja['loja']} ({loja['segmento']})" if loja.get("segmento") else loja["loja"]


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
    meses = ["jun", "jul", "ago", "set", "out"]
    tabela = []
    for i, loja in enumerate(lojas):
        lin, col = i // colunas + 1, i % colunas + 1
        x = [m["mes"] for m in loja["meses"]]
        for medida, cor, traco in (("faturamento", COR_DESTAQUE, "solid"), ("pedidos", COR_PAR, "dot")):
            y = [m["indice"][medida] for m in loja["meses"]]
            fig.add_trace(go.Scatter(
                x=x, y=y, mode="lines+markers", name=medida.capitalize(), legendgroup=medida, showlegend=i == 0,
                line=dict(color=cor, width=2, dash=traco), marker=dict(size=8, color=cor, line=dict(color="#ffffff", width=2)),
                hovertemplate=f"{loja['loja']} · %{{x}}<br>{medida.capitalize()}: %{{y:.1f}}<extra></extra>",
            ), row=lin, col=col)
        fig.add_hline(y=100, line=dict(color=TINTA_SECUNDARIA, width=1, dash="dash"), opacity=0.5, row=lin, col=col)
        fim = loja["meses"][-1]
        tabela.append((f"{loja['loja']}, {x[0]} a {x[-1]}",
                       f"faturamento {decimal_br(fim['indice']['faturamento'])}, pedidos {decimal_br(fim['indice']['pedidos'])}"))
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
        nomes = [e["etapa"] for e in m["funil"]]
        valores = [e["pct"] for e in m["funil"]]
        fig.add_trace(go.Bar(
            x=valores, y=nomes, orientation="h", visible=i == ativo,
            marker=dict(color=[COR_SERIE] * (len(valores) - 1) + [COR_DESTAQUE], cornerradius=4),
            text=[percentual_br(v) for v in valores], textposition="outside", textfont=dict(color=TINTA), cliponaxis=False,
            hovertemplate=f"{loja['loja']} · {m['mes']}<br>%{{y}}: %{{x:.1f}}% das visitas<extra></extra>",
        ))
    rotulos = [f"{l['loja']} · {m['mes']}" for l, m in opcoes]
    fig.update_layout(**layout_base(height=260, bargap=0.4, margin=dict(l=8, r=24, t=8, b=36),
                                    meta=seletor("Loja e mês", [(nome_loja(l), r) for (l, m), r in zip(opcoes, rotulos)],
                                                 [[j == i for j in range(len(opcoes))] for i in range(len(opcoes))], ativo)))
    fig.update_yaxes(autorange="reversed", automargin=True, tickfont=dict(color=TINTA_SECUNDARIA), ticksuffix="  ")
    fig.update_xaxes(showgrid=True, gridcolor=GRADE, zeroline=False, automargin=True, range=[0, 118], ticksuffix="%",
                     tickfont=dict(color=TINTA_SECUNDARIA))
    tabela = [(r, f"{percentual_br(m['funil'][-1]['pct'])} das visitas viraram pedido") for r, (l, m) in zip(rotulos, opcoes)]
    return fig, tabela


def grafico_variacao(dados):
    """Lojas nas linhas, meses nas colunas, uma opção por medida."""
    medidas = [("faturamento", "Faturamento", "%"), ("pedidos", "Pedidos", "%"), ("ticket", "Ticket médio", "%"),
               ("conversao_pp", "Conversão", " p.p.")]
    meses = ["jul", "ago", "set", "out"]
    lojas = dados["lojas"]
    fig = go.Figure()
    for i, (chave, rotulo, sufixo) in enumerate(medidas):
        z, texto = [], []
        for loja in lojas:
            por_mes = {m["mes"]: m["variacao"][chave] for m in loja["meses"] if "variacao" in m}
            z.append([por_mes.get(mes) for mes in meses])
            texto.append([(("+" if v > 0 else "") + decimal_br(v) + sufixo) if v is not None else ""
                          for v in z[-1]])
        limite = 10 if chave == "conversao_pp" else 40
        fig.add_trace(go.Heatmap(
            z=z, x=meses, y=[l["loja"] for l in lojas], text=texto, texttemplate="%{text}", visible=i == 0,
            textfont=dict(color=TINTA, size=13), colorscale=DIVERGENTE, zmid=0, zmin=-limite, zmax=limite,
            showscale=False, xgap=2, ygap=2, hoverongaps=False,
            hovertemplate=f"%{{y}} · %{{x}} contra o mês anterior<br>{rotulo}: %{{text}}<extra></extra>",
        ))
    fig.update_layout(**layout_base(height=380, margin=dict(l=8, r=8, t=8, b=36),
                                    meta=seletor("Medida", [(None, m[1]) for m in medidas],
                                                 [[j == i for j in range(len(medidas))] for i in range(len(medidas))])))
    fig.update_yaxes(autorange="reversed", automargin=True, showgrid=False, ticks="", tickfont=dict(color=TINTA_SECUNDARIA),
                     ticksuffix="  ")
    fig.update_xaxes(automargin=True, showgrid=False, tickfont=dict(color=TINTA_SECUNDARIA))
    tabela = [(f"{l['loja']} · {m['mes']}", f"faturamento {sinal_br(m['variacao']['faturamento'])}, "
               f"pedidos {sinal_br(m['variacao']['pedidos'])}")
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
        customdata=[f"{p['dia'][8:]}/{p['dia'][5:7]} ({p['dia_semana']})" for p in pontos],
        hovertemplate="%{customdata}<br>índice %{y:.0f}<extra></extra>",
    ))
    fig.add_hline(y=100, line=dict(color=TINTA_SECUNDARIA, width=1, dash="dash"), opacity=0.6,
                  annotation_text="ago = 100" if estreito else "média de ago = 100", annotation_position="right",
                  annotation_font=dict(color=TINTA_SECUNDARIA, size=12))
    for e in caso["eventos"]:
        fig.add_vline(x=e["dia"], line=dict(color=TINTA, width=1.5))
        rotulo = e["dia"][8:] + "/" + e["dia"][5:7] if estreito else e["rotulo"]
        fig.add_annotation(x=e["dia"], y=1, yref="paper", text=rotulo, showarrow=False, xanchor="left", xshift=4,
                           yanchor="top", font=dict(color=TINTA, size=12), bgcolor="rgba(255,255,255,.85)")
    fig.update_layout(**layout_base(height=300, bargap=0.25, margin=dict(l=8, r=64 if estreito else 120, t=16, b=36)))
    eixos_discretos(fig, type="date", tickformat="%d/%m", dtick=(14 if estreito else 7) * 86400000, tick0="2026-08-03",
                    tickangle=0)
    fig.update_yaxes(title=dict(text="pedidos por dia, índice", font=dict(color=TINTA_SECUNDARIA, size=12)))

    def media(a, b):
        v = [p["indice"] for p in pontos if a <= p["dia"] <= b and p["indice"] is not None]
        return sum(v) / len(v)
    tabela = [("01 a 05/08", decimal_br(media('2026-08-01', '2026-08-05'))),
              ("06/08 a 04/09", decimal_br(media('2026-08-06', '2026-09-04'))),
              ("05 a 13/09, depois da reordenação", decimal_br(media(*janela))),
              ("15 a 30/09", decimal_br(media('2026-09-15', '2026-09-30')))]
    return fig, tabela


def grafico_a_contra_b(dados):
    """Faturamento e pedidos de set contra ago nas duas lojas da mesma cozinha."""
    lojas = [("Loja A", "com anúncio"), ("Loja B", "sem anúncio")]
    por_loja = {l["loja"]: next(m for m in l["meses"] if m["mes"] == "set")["variacao"]
                for l in dados["lojas"] if l["loja"] in dict(lojas)}
    fig = go.Figure()
    for medida, cor in (("faturamento", COR_DESTAQUE), ("pedidos", COR_PAR)):
        valores = [por_loja[l][medida] for l, _ in lojas]
        fig.add_trace(go.Bar(
            x=[f"{l}<br>{c}" for l, c in lojas], y=valores, name=medida.capitalize(),
            marker=dict(color=cor, cornerradius=4), text=[sinal_br(v) for v in valores], textposition="outside",
            textfont=dict(color=TINTA), cliponaxis=False,
            hovertemplate=f"%{{x}}<br>{medida.capitalize()}: %{{text}} em set contra ago<extra></extra>",
        ))
    fig.update_layout(**layout_base(height=300, barmode="group", bargap=0.35, bargroupgap=0.12,
                                    margin=dict(l=8, r=16, t=40, b=36)))
    fig.update_layout(showlegend=True, legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom",
                                                   font=dict(color=TINTA_SECUNDARIA)))
    eixos_discretos(fig)
    fig.update_yaxes(ticksuffix="%", range=[0, 85])
    tabela = [(f"{l}, {c}", f"faturamento {sinal_br(por_loja[l]['faturamento'])}, pedidos {sinal_br(por_loja[l]['pedidos'])}")
              for l, c in lojas]
    return fig, tabela


def grafico_semana_pagamento(dados, estreito=False):
    """Participação por dia da semana e por forma de pagamento no último mês de cada loja."""
    lojas = dados["lojas"]
    fig = make_subplots(rows=2, cols=1, vertical_spacing=0.2,
                        subplot_titles=["Por dia da semana", "Por forma de pagamento"] if estreito
                        else ["Pedidos por dia da semana", "Pedidos por forma de pagamento"])
    ordem_pag = ["Pix", "Crédito", "Débito", "Carteira digital", "Vale-refeição", "Dinheiro", "Outros"]
    ativo = next(i for i, l in enumerate(lojas) if l["loja"] == "Loja B")
    visiveis = []
    for i, loja in enumerate(lojas):
        m = loja["meses"][-1]
        dias = list(m["dias"])
        fig.add_trace(go.Bar(x=dias, y=[m["dias"][d] for d in dias], visible=i == ativo,
                             marker=dict(color=COR_SERIE, cornerradius=3),
                             text=[f"{m['dias'][d]:.0f}%" if estreito else percentual_br(m["dias"][d]) for d in dias],
                             textposition="outside", textangle=0, textfont=dict(color=TINTA, size=11 if estreito else 12),
                             cliponaxis=False,
                             hovertemplate=f"{loja['loja']} · {m['mes']}<br>%{{x}}: %{{y:.1f}}%<extra></extra>"), row=1, col=1)
        pag = [p for p in ordem_pag if m["pagamento"].get(p)]
        fig.add_trace(go.Bar(x=[m["pagamento"][p] for p in pag], y=pag, orientation="h", visible=i == ativo,
                             marker=dict(color=COR_SERIE, cornerradius=3), text=[percentual_br(m["pagamento"][p]) for p in pag],
                             textposition="outside", textfont=dict(color=TINTA, size=12), cliponaxis=False,
                             hovertemplate=f"{loja['loja']} · {m['mes']}<br>%{{y}}: %{{x:.1f}}%<extra></extra>"), row=2, col=1)
        visiveis.append([j // 2 == i for j in range(2 * len(lojas))])
    rotulos = [f"{l['loja']} · {l['meses'][-1]['mes']}" for l in lojas]
    fig.update_layout(**layout_base(height=560, bargap=0.3, margin=dict(l=8, r=24, t=40, b=24),
                                    meta=seletor("Loja", [(None, f"{nome_loja(l)} · {l['meses'][-1]['mes']}") for l in lojas],
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
        tabela.append((r, f"dia mais forte {dia} ({percentual_br(m['dias'][dia])}), Pix {percentual_br(m['pagamento'].get('Pix', 0))}"))
    return fig, tabela


GRAFICOS = {
    "funil-coleta": grafico_funil_coleta,
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


# ---------------------------------------------------------------- build

def ambiente():
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True,
                      undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    return env


def escrever(caminho, texto):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")


def build():
    perfil = carregar_toml(CONTEUDO / "perfil.toml")
    projetos = carregar_projetos()
    env = ambiente()

    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(STATIC, DIST / "static")

    usa_plotly = False
    for p in projetos:
        p["graficos_montados"] = montar_graficos(p)
        if any("figura" in g for g in p["graficos_montados"]):
            usa_plotly = True
    if usa_plotly:
        escrever(DIST / "static" / "vendor" / "plotly.min.js", get_plotlyjs())

    comum = dict(perfil=perfil, projetos=projetos)
    escrever(DIST / "index.html", env.get_template("index.html").render(**comum, pagina="inicio"))
    for p in projetos:
        html = env.get_template("projeto.html").render(**comum, projeto=p, pagina=p["slug"])
        escrever(DIST / "projetos" / p["slug"] / "index.html", html)
    escrever(DIST / "404.html", env.get_template("404.html").render(**comum, pagina="404"))

    print(f"Site gerado em {DIST}")
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
EXTENSOES_TEXTO = {".html", ".json", ".css", ".js", ".txt", ".toml", ".xml", ".svg"}


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
    for pasta in (DADOS, DIST, CONTEUDO):
        if not pasta.exists():
            continue
        for arq in pasta.rglob("*"):
            if arq.is_file() and arq.suffix in EXTENSOES_TEXTO and "vendor" not in arq.parts:
                yield arq


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
        texto = arq.read_text(encoding="utf-8", errors="ignore")
        rel = arq.relative_to(RAIZ)
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
    perfil = carregar_toml(CONTEUDO / "perfil.toml")
    pendencias = []
    if not perfil.get("cv"):
        pendencias.append("perfil: CV em PDF ainda não escolhido")
    for p in carregar_projetos():
        if p.get("repositorio_pendente"):
            pendencias.append(f"{p['slug']}: {p['repositorio_pendente']}")
        for g in p.get("graficos", []):
            if "pendente" in g:
                pendencias.append(f"{p['slug']}: gráfico '{g['titulo']}': {g['pendente']}")
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
        pagina = DIST / "404.html"
        if code == 404 and pagina.exists():
            corpo = pagina.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        super().send_error(code, message, explain)


def serve(porta):
    build()
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), partial(Handler, directory=str(DIST)))
    print(f"Servindo em http://localhost:{porta} (Ctrl+C para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description="Site do portfólio")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("build", help="gera dist/")
    serve_p = sub.add_parser("serve", help="gera e serve localmente")
    serve_p.add_argument("--porta", type=int, default=8000)
    sub.add_parser("verificar", help="procura dado sensível e lista pendências")
    args = parser.parse_args()

    if args.comando == "build":
        build()
    elif args.comando == "serve":
        serve(args.porta)
    else:
        verificar()


if __name__ == "__main__":
    main()
