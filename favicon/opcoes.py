"""Gera 3 opções do favicon "pb", cada uma numa tipografia, para o Pedro escolher.

    .venv/bin/python favicon/opcoes.py
    node favicon/gerar.mjs <chrome> static/favicon/opcoes/<opção>   (PNG e ICO de cada opção)

As letras saem da fonte como contorno (path) no SVG: o favicon não depende de fonte instalada.
Fontes: as do próprio site, em static/fonts, todas com licença SIL Open Font License (LICENSE-*.txt ao lado).
Precisa do fontTools e do brotli (para ler woff2): .venv/bin/python -m pip install fonttools brotli

Mesma ideia do favicon atual: fundo azul-marinho da capa, p branco e b no azul e lilás do gradiente do site,
e as hastes do p (desce) e do b (sobe) lidas como duas barras de gráfico desencontradas.

Cada opção tem três desenhos, em static/favicon/opcoes/<n>-<fonte>/:
  favicon.svg           32 px para cima (aba em tela de alta densidade, favoritos)
  favicon-16.svg        16 px, letras maiores e traço reforçado, com a haste do p e o topo do b presos à grade
  apple-touch-icon.svg  tela inicial do iPhone (fundo até a borda, monograma com folga)
A pasta opcoes/ não vai para o site (o build pula).

A opção em ESCOLHIDA é o favicon do site: o script grava também o favicon.svg dela em static/favicon/
e os desenhos de 16 px e do iPhone em favicon/. Depois, node favicon/gerar.mjs <chrome> (sem pasta)
refaz favicon-32.png, apple-touch-icon.png e favicon.ico em static/favicon/.
"""

from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.pointInsidePen import PointInsidePen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

RAIZ = Path(__file__).resolve().parent.parent
FONTES = RAIZ / "static" / "fonts"
SAIDA = RAIZ / "static" / "favicon" / "opcoes"
SITE = RAIZ / "static" / "favicon"  # favicon.svg do site
CONFERENCIA = RAIZ / "favicon"  # 16 px e iPhone em SVG, lidos pelo gerar.mjs

ESCOLHIDA = "3-jetbrains-mono"  # escolha do Pedro em 24/11/2026

MARINHO = "#0f1d3a"  # fundo da .capa em tema-vitrine.css
BRANCO = "#ffffff"
AZUL_CLARO = "#8fa3ff"  # #3d5af1 do site, clareado para o fundo escuro
LILAS_CLARO = "#c0a6ff"  # #7c4dff do site, clareado
MEIO = "#a9a5ff"  # cor única do b no 16 px: em 2 px de traço o degradê não aparece

# espaco: distância entre o p e o b, em fração do corpo (em); espaco16 vale para o desenho de 16 px,
# que pede folga maior para sobrar ao menos 1 pixel de fundo entre as letras.
# reforco32: traço da mesma cor em volta da letra, em px do desenho (engrossa o peso 600);
# no 16 px o reforço é calculado para a haste fechar em 2 px.
OPCOES = [
    dict(slug="1-space-grotesk", nome="Space Grotesk", arquivo="space-grotesk-latin-600-normal.woff2",
         espaco=0.08, espaco16=0.14, reforco32=0.5, margem32=4, margem16=1),
    dict(slug="2-fraunces", nome="Fraunces", arquivo="fraunces-latin-600-normal.woff2",
         espaco=0.03, espaco16=0.08, reforco32=0.4, margem32=3.5, margem16=0.75),
    dict(slug="3-jetbrains-mono", nome="JetBrains Mono", arquivo="jetbrains-mono-latin-600-normal.woff2",
         espaco=0.07, espaco16=0.16, reforco32=0.4, margem32=4.5, margem16=1),
]


def num(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def haste(conjunto, nome, caixa, letra):
    """Borda esquerda e largura da haste, varrendo a letra na altura da descendente (p) ou da ascendente (b)."""
    x0, y0, x1, y1 = caixa
    y = y0 / 2 if letra == "p" else y1 * 0.85
    dentro = []
    for x in range(int(x0), int(x1)):
        pen = PointInsidePen(conjunto, (x + 0.5, y))
        conjunto[nome].draw(pen)
        dentro.append(pen.getResult())
    ini = dentro.index(True)
    return int(x0) + ini, dentro.index(False, ini) - ini


def glifos(arquivo):
    fonte = TTFont(FONTES / arquivo)
    conjunto = fonte.getGlyphSet()
    cmap = fonte.getBestCmap()
    saida = {}
    for letra in "pb":
        nome = cmap[ord(letra)]
        bp = BoundsPen(conjunto)
        conjunto[nome].draw(bp)
        saida[letra] = (conjunto, nome, bp.bounds, haste(conjunto, nome, bp.bounds, letra))
    return saida, fonte["head"].unitsPerEm


def caminho(conjunto, nome, escala, dx, dy):
    """Contorno do glifo em coordenadas do SVG (y para baixo)."""
    pen = SVGPathPen(conjunto, ntos=num)
    conjunto[nome].draw(TransformPen(pen, (escala, 0, 0, -escala, dx, dy)))
    return pen.getCommands()


def prender_na_grade(v):
    """Quanto falta para v cair em pixel inteiro."""
    return round(v) - v


def montar(op, lado, margem, reforco, prender, fator=1.0):
    """Posiciona p e b centrados no quadrado.

    Devolve os dois contornos, a caixa do b (para o gradiente) e o reforço usado. No 16 px (prender=True)
    o reforço é calculado para a haste fechar em 2 px inteiros, e a haste do p, a do b e o topo do b
    caem na grade de pixels: é o que mantém as barras nítidas na aba.
    """
    g, upm = glifos(op["arquivo"])
    (_, _, (px0, py0, px1, py1), (hp, larg_haste)), (_, _, (bx0, by0, bx1, by1), (hb, _)) = g["p"], g["b"]
    espaco = op["espaco16" if prender else "espaco"] * upm
    largura = (px1 - px0) + espaco + (bx1 - bx0)
    altura = by1 - py0  # topo do b até o pé do p
    for _ in range(4):  # reforço e escala dependem um do outro: poucas voltas bastam
        escala = (lado - 2 * margem - reforco) * fator / max(largura, altura)
        if prender:
            reforco = max(2 - larg_haste * escala, 0)
    x0 = (lado - largura * escala) / 2 - px0 * escala
    # linha de base: o conjunto (topo do b ao pé do p) centrado na vertical
    base = (lado - altura * escala) / 2 + by1 * escala
    xb = x0 + (px1 - px0 + espaco) * escala - (bx0 - px0) * escala
    if prender:
        x0 += prender_na_grade(x0 + hp * escala - reforco / 2)
        xb += prender_na_grade(xb + hb * escala - reforco / 2)
        base += prender_na_grade(base - by1 * escala - reforco / 2)
    dp = caminho(g["p"][0], g["p"][1], escala, x0, base)
    db = caminho(g["b"][0], g["b"][1], escala, xb, base)
    caixa_b = (xb + bx0 * escala, base - by1 * escala, xb + bx1 * escala, base - by0 * escala)
    return dp, db, caixa_b, reforco


def svg(op, lado, raio, margem, reforco, prender, comentario, fator=1.0, gradiente=True):
    dp, db, (bx0, by0, bx1, by1), reforco = montar(op, lado, margem, reforco, prender, fator)
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}">', f"  <!-- {comentario} -->"]
    if gradiente:
        partes += [
            "  <defs>",
            f'    <linearGradient id="g" gradientUnits="userSpaceOnUse" x1="{num(bx0)}" y1="{num(by1)}" '
            f'x2="{num(bx1)}" y2="{num(by0)}">',
            f'      <stop offset="0" stop-color="{AZUL_CLARO}"/>',
            f'      <stop offset="1" stop-color="{LILAS_CLARO}"/>',
            "    </linearGradient>",
            "  </defs>",
        ]
        cor_b = "url(#g)"
    else:
        cor_b = MEIO
    raio_attr = f' rx="{num(raio)}"' if raio else ""
    partes.append(f'  <rect width="{lado}" height="{lado}"{raio_attr} fill="{MARINHO}"/>')

    def letra(d, cor):
        traco = (f' stroke="{cor}" stroke-width="{num(reforco)}" stroke-linejoin="round"' if reforco else "")
        return f'  <path d="{d}" fill="{cor}"{traco}/>'

    partes += [letra(dp, BRANCO), letra(db, cor_b), "</svg>", ""]
    return "\n".join(partes)


def main():
    for op in OPCOES:
        pasta = SAIDA / op["slug"]
        pasta.mkdir(parents=True, exist_ok=True)
        base = f'Monograma "pb" em {op["nome"]} (SIL Open Font License), letras convertidas em contorno.'
        (pasta / "favicon.svg").write_text(svg(
            op, 32, 7, op["margem32"], op["reforco32"], False,
            base + " Gerado por favicon/opcoes.py."), encoding="utf-8")
        (pasta / "favicon-16.svg").write_text(svg(
            op, 16, 3.5, op["margem16"], 0, True,
            base + " Desenho de 16 px (vai dentro do favicon.ico). Gerado por favicon/opcoes.py.",
            gradiente=False), encoding="utf-8")
        (pasta / "apple-touch-icon.svg").write_text(svg(
            op, 32, 0, op["margem32"], op["reforco32"], False,
            base + " Tela inicial do iPhone. Gerado por favicon/opcoes.py.", fator=0.8), encoding="utf-8")
        print(f"ok: {pasta.relative_to(RAIZ)}")
        if op["slug"] == ESCOLHIDA:
            for nome, destino in (("favicon.svg", SITE), ("favicon-16.svg", CONFERENCIA),
                                  ("apple-touch-icon.svg", CONFERENCIA)):
                (destino / nome).write_text((pasta / nome).read_text(encoding="utf-8"), encoding="utf-8")
            print(f"favicon do site: {op['nome']} em static/favicon/favicon.svg e favicon/*.svg")


if __name__ == "__main__":
    main()
