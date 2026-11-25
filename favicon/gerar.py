"""Primeiro desenho do favicon (barras geométricas), substituído em 24/11/2026 pelo "pb" em JetBrains Mono.

Não rode para o site atual: ele sobrescreve o favicon novo com este desenho antigo.
O favicon do site hoje sai de favicon/opcoes.py (opção ESCOLHIDA) mais node favicon/gerar.mjs <chrome>.
Fica guardado como referência do desenho anterior.

    python favicon/gerar.py

Desenho: monograma "pb" em que a haste do p (para baixo) e a do b (para cima) ficam como duas barras
de gráfico. Fundo no azul-marinho da capa do tema vitrine; o b no azul e lilás do gradiente do site,
clareados para ler no fundo escuro.

Saída em static/favicon/ (vai para o site): favicon.svg, favicon-32.png, apple-touch-icon.png (180)
e favicon.ico (16, 32 e 48). O build copia o favicon.ico também para a raiz, onde o navegador procura sozinho.
Em favicon/ ficam só para conferência o desenho de 16 px e o da tela do iPhone em SVG.

O de 16 px tem desenho próprio, na grade de 16, para cada traço cair inteiro num pixel.
Os PNG saem de uma rasterização simples com 8x8 amostras por pixel (antisserrilhado), suficiente para
retângulos e anéis.
"""

import struct
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "static" / "favicon"
CONFERENCIA = RAIZ / "favicon"

MARINHO = (0x0F, 0x1D, 0x3A)  # #0f1d3a, o fundo da .capa em tema-vitrine.css
BRANCO = (0xFF, 0xFF, 0xFF)
# pontas do gradiente do b: #3d5af1 e #7c4dff do site, clareados para contraste no marinho
AZUL_CLARO = (0x8F, 0xA3, 0xFF)
LILAS_CLARO = (0xC0, 0xA6, 0xFF)
# o de 16 px usa uma cor só, o meio do gradiente: em 2 px de traço o degradê não aparece
MEIO = (0xA9, 0xA5, 0xFF)


def hexa(cor):
    return "#%02x%02x%02x" % cor


# ---------------------------------------------------------------- desenhos
# Formas: ("ret", x, y, l, a, raio, tinta) preenchido e ("contorno", x, y, l, a, raio, traço, tinta)
# com o traço centrado na borda, como no SVG. Círculo = contorno com raio igual à metade do lado.
# Tinta: uma cor ou ("gradiente", x1, y1, x2, y2), do azul claro ao lilás claro.

GRAD_B = ("gradiente", 17, 21, 27, 5)

PB_32 = [
    ("ret", 5, 11, 3, 16, 0, BRANCO),                       # haste do p, desce
    ("contorno", 6.5, 12.5, 7, 7, 3.5, 3, BRANCO),          # bojo do p
    ("ret", 17, 5, 3, 16, 0, GRAD_B),                       # haste do b, sobe
    ("contorno", 18.5, 12.5, 7, 7, 3.5, 3, GRAD_B),         # bojo do b
]

PB_16 = [
    ("ret", 1, 5, 2, 9, 0, BRANCO),
    ("contorno", 2, 6, 4, 4, 1.5, 2, BRANCO),
    ("ret", 9, 2, 2, 9, 0, MEIO),
    ("contorno", 10, 6, 4, 4, 1.5, 2, MEIO),
]


def com_fundo(formas, lado, raio):
    return [("ret", 0, 0, lado, lado, raio, MARINHO)] + formas


def escalar(formas, fator, centro):
    """Reduz o monograma em volta do centro (tela do iPhone, que pede folga)."""
    def p(v, eixo=True):
        return centro + (v - centro) * fator if eixo else v * fator
    saida = []
    for f in formas:
        tinta = f[-1]
        if isinstance(tinta, tuple) and tinta[0] == "gradiente":
            tinta = ("gradiente", p(tinta[1]), p(tinta[2]), p(tinta[3]), p(tinta[4]))
        if f[0] == "ret":
            _, x, y, l, a, r, _t = f
            saida.append(("ret", p(x), p(y), l * fator, a * fator, r * fator, tinta))
        else:
            _, x, y, l, a, r, t, _t = f
            saida.append(("contorno", p(x), p(y), l * fator, a * fator, r * fator, t * fator, tinta))
    return saida


FAVICON = com_fundo(PB_32, 32, 7)
FAVICON_16 = com_fundo(PB_16, 16, 3.5)
# o iOS arredonda o ícone sozinho: fundo até a borda
APPLE = [("ret", 0, 0, 32, 32, 0, MARINHO)] + escalar(PB_32, 0.74, 16)


# ---------------------------------------------------------------- SVG

def svg(formas, lado, comentario):
    defs, corpo = [], []
    for f in formas:
        tinta = f[-1]
        if isinstance(tinta, tuple) and tinta[0] == "gradiente":
            if not defs:
                _, x1, y1, x2, y2 = tinta
                defs.append(
                    f'    <linearGradient id="g" gradientUnits="userSpaceOnUse" x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}">\n'
                    f'      <stop offset="0" stop-color="{hexa(AZUL_CLARO)}"/>\n'
                    f'      <stop offset="1" stop-color="{hexa(LILAS_CLARO)}"/>\n'
                    f'    </linearGradient>')
            cor = "url(#g)"
        else:
            cor = hexa(tinta)
        if f[0] == "ret":
            _, x, y, l, a, r, _t = f
            raio = f' rx="{r:g}"' if r else ""
            corpo.append(f'  <rect x="{x:g}" y="{y:g}" width="{l:g}" height="{a:g}"{raio} fill="{cor}"/>')
        else:
            _, x, y, l, a, r, t, _t = f
            if l == a and r == l / 2:
                corpo.append(f'  <circle cx="{x + r:g}" cy="{y + r:g}" r="{r:g}" fill="none" stroke="{cor}" stroke-width="{t:g}"/>')
            else:
                corpo.append(f'  <rect x="{x:g}" y="{y:g}" width="{l:g}" height="{a:g}" rx="{r:g}" fill="none" '
                             f'stroke="{cor}" stroke-width="{t:g}"/>')
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}">', f"  <!-- {comentario} -->"]
    if defs:
        partes += ["  <defs>", *defs, "  </defs>"]
    return "\n".join(partes + corpo + ["</svg>", ""])


# ---------------------------------------------------------------- rasterização

def dentro_ret(px, py, x, y, l, a, r):
    if not (x <= px <= x + l and y <= py <= y + a):
        return False
    if r <= 0:
        return True
    dx = max(x + r - px, 0, px - (x + l - r))
    dy = max(y + r - py, 0, py - (y + a - r))
    return dx * dx + dy * dy <= r * r


def contem(forma, px, py):
    if forma[0] == "ret":
        _, x, y, l, a, r, _t = forma
        return dentro_ret(px, py, x, y, l, a, r)
    _, x, y, l, a, r, t, _t = forma
    m = t / 2
    return (dentro_ret(px, py, x - m, y - m, l + t, a + t, r + m)
            and not dentro_ret(px, py, x + m, y + m, l - t, a - t, max(r - m, 0)))


def cor_em(tinta, px, py):
    if not (isinstance(tinta, tuple) and tinta[0] == "gradiente"):
        return tinta
    _, x1, y1, x2, y2 = tinta
    vx, vy = x2 - x1, y2 - y1
    s = min(max(((px - x1) * vx + (py - y1) * vy) / (vx * vx + vy * vy), 0), 1)
    return tuple(a + (b - a) * s for a, b in zip(AZUL_CLARO, LILAS_CLARO))


def rasterizar(formas, lado_desenho, lado_px, amostras=8):
    escala = lado_desenho / lado_px
    linhas = []
    passo = 1 / amostras
    for j in range(lado_px):
        linha = bytearray([0])  # filtro PNG "nenhum"
        for i in range(lado_px):
            soma = [0.0, 0.0, 0.0]
            cobertas = 0
            for sj in range(amostras):
                py = (j + (sj + 0.5) * passo) * escala
                for si in range(amostras):
                    px = (i + (si + 0.5) * passo) * escala
                    # todas as tintas são opacas: vale a última forma que cobre o ponto
                    for forma in reversed(formas):
                        if contem(forma, px, py):
                            c = cor_em(forma[-1], px, py)
                            soma[0] += c[0]
                            soma[1] += c[1]
                            soma[2] += c[2]
                            cobertas += 1
                            break
            if cobertas:
                linha += bytes(round(v / cobertas) for v in soma) + bytes([round(255 * cobertas / amostras ** 2)])
            else:
                linha += bytes(4)
        linhas.append(bytes(linha))
    return png(lado_px, b"".join(linhas))


def png(lado, dados):
    def bloco(tipo, conteudo):
        return (struct.pack(">I", len(conteudo)) + tipo + conteudo
                + struct.pack(">I", zlib.crc32(tipo + conteudo) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", struct.pack(">IIBBBBB", lado, lado, 8, 6, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(dados, 9))
            + bloco(b"IEND", b""))


def ico(imagens):
    """ICO com PNG dentro, aceito por todo navegador atual e pelo Windows desde o Vista."""
    cabecalho = struct.pack("<HHH", 0, 1, len(imagens))
    entradas, deslocamento = [], 6 + 16 * len(imagens)
    for lado, dados in imagens:
        entradas.append(struct.pack("<BBBBHHII", lado % 256, lado % 256, 0, 0, 1, 32, len(dados), deslocamento))
        deslocamento += len(dados)
    return cabecalho + b"".join(entradas) + b"".join(d for _, d in imagens)


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / "favicon.svg").write_text(svg(FAVICON, 32, (
        'Monograma "pb": as hastes do p e do b como duas barras de grafico, '
        "no azul-marinho da capa do tema vitrine. Gerado por favicon/gerar.py.")), encoding="utf-8")
    (CONFERENCIA / "favicon-16.svg").write_text(svg(FAVICON_16, 16, (
        "Desenho de 16 px do favicon, so para conferencia (vai dentro do favicon.ico). Gerado por favicon/gerar.py.")),
        encoding="utf-8")
    (CONFERENCIA / "apple-touch-icon.svg").write_text(svg(APPLE, 32, (
        "Icone da tela inicial do iPhone, so para conferencia. Gerado por favicon/gerar.py.")), encoding="utf-8")

    p16 = rasterizar(FAVICON_16, 16, 16)
    p32 = rasterizar(FAVICON, 32, 32)
    p48 = rasterizar(FAVICON, 32, 48)
    (SAIDA / "favicon-32.png").write_bytes(p32)
    (SAIDA / "apple-touch-icon.png").write_bytes(rasterizar(APPLE, 32, 180, amostras=4))
    (SAIDA / "favicon.ico").write_bytes(ico([(16, p16), (32, p32), (48, p48)]))
    (CONFERENCIA / "favicon-16.png").write_bytes(p16)
    print(f"Favicon gerado em {SAIDA.relative_to(RAIZ)}: favicon.svg, favicon-32.png, apple-touch-icon.png, favicon.ico")


if __name__ == "__main__":
    main()
