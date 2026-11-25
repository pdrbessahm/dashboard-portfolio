"""Gera os PNG e o ICO do favicon a partir dos SVG, em Python puro, sem navegador nem biblioteca de imagem.

    .venv/bin/python favicon/rasterizar.py [pasta]

Faz o mesmo que node favicon/gerar.mjs <chrome>, para quando o Chromium não está à mão.
Lê static/favicon/favicon.svg (32 px para cima), favicon/favicon-16.svg (desenho próprio da grade de 16 px)
e favicon/apple-touch-icon.svg (tela inicial do iPhone).
Grava em static/favicon/: favicon-32.png, apple-touch-icon.png e favicon.ico (16, 32 e 48 px),
e o favicon-16.png de conferência em favicon/.
Com [pasta] (ex.: static/favicon/opcoes/3-jetbrains-mono), lê e grava tudo nessa pasta.

Entende só o que favicon/opcoes.py escreve: <rect> com rx, <path> com comandos absolutos M, L, H, V, Q e Z,
preenchimento e traço (junção redonda) numa cor ou num <linearGradient> de dois pontos em userSpaceOnUse.
Antisserrilhado por supersampling (8x8 amostras por pixel; 4x4 no de 180 px). Fundo fora do desenho fica transparente.
"""

import math
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NS = "{http://www.w3.org/2000/svg}"
PASSOS_CURVA = 12  # segmentos de reta por curva quadrática


def cor_hex(v):
    v = v.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- leitura do SVG

def ler_path(d):
    """Contornos do path como listas de pontos (curvas já quebradas em retas)."""
    fichas = re.findall(r"[MLHVQZ]|-?\d*\.?\d+(?:e-?\d+)?", d)
    contornos, atual = [], []
    x = y = 0.0
    i = 0
    cmd = None
    while i < len(fichas):
        if fichas[i].isalpha():
            cmd = fichas[i]
            i += 1
            if cmd == "Z":
                if atual:
                    contornos.append(atual)
                atual = []
                continue
        n = lambda k: float(fichas[i + k])  # noqa: E731
        if cmd == "M":
            if atual:
                contornos.append(atual)
            x, y = n(0), n(1)
            atual = [(x, y)]
            i += 2
            cmd = "L"  # pares seguidos de um M valem como L
        elif cmd == "L":
            x, y = n(0), n(1)
            atual.append((x, y))
            i += 2
        elif cmd == "H":
            x = n(0)
            atual.append((x, y))
            i += 1
        elif cmd == "V":
            y = n(0)
            atual.append((x, y))
            i += 1
        elif cmd == "Q":
            cx, cy, ex, ey = n(0), n(1), n(2), n(3)
            for k in range(1, PASSOS_CURVA + 1):
                t = k / PASSOS_CURVA
                u = 1 - t
                atual.append((u * u * x + 2 * u * t * cx + t * t * ex, u * u * y + 2 * u * t * cy + t * t * ey))
            x, y = ex, ey
            i += 4
        else:
            raise ValueError(f"comando de path não suportado: {cmd}")
    if atual:
        contornos.append(atual)
    return contornos


def ler_svg(caminho):
    raiz = ET.parse(caminho).getroot()
    lado = float(raiz.get("viewBox").split()[2])
    gradientes = {}
    for g in raiz.iter(NS + "linearGradient"):
        paradas = sorted((float(s.get("offset")), cor_hex(s.get("stop-color"))) for s in g.iter(NS + "stop"))
        gradientes[g.get("id")] = (float(g.get("x1")), float(g.get("y1")), float(g.get("x2")), float(g.get("y2")),
                                   paradas[0][1], paradas[-1][1])

    def tinta(v):
        if v is None or v == "none":
            return None
        m = re.fullmatch(r"url\(#(.+)\)", v)
        return gradientes[m.group(1)] if m else cor_hex(v)

    formas = []
    for el in raiz:
        if el.tag == NS + "rect":
            formas.append(Retangulo(float(el.get("x", 0)), float(el.get("y", 0)), float(el.get("width")),
                                    float(el.get("height")), float(el.get("rx", 0)), tinta(el.get("fill"))))
        elif el.tag == NS + "path":
            formas.append(Caminho(ler_path(el.get("d")), tinta(el.get("fill")), tinta(el.get("stroke")),
                                  float(el.get("stroke-width", 0))))
    return lado, formas


# ---------------------------------------------------------------- formas

class Retangulo:
    def __init__(self, x, y, l, a, r, tinta):
        self.x, self.y, self.l, self.a, self.r, self.tinta = x, y, l, a, r, tinta

    def preparar_linha(self, py):
        pass

    def tinta_em(self, px, py):
        x, y, l, a, r = self.x, self.y, self.l, self.a, self.r
        if not (x <= px <= x + l and y <= py <= y + a):
            return None
        if r > 0:
            dx = max(x + r - px, 0, px - (x + l - r))
            dy = max(y + r - py, 0, py - (y + a - r))
            if dx * dx + dy * dy > r * r:
                return None
        return self.tinta


class Caminho:
    """Preenchimento pela regra nonzero (padrão do SVG) e traço centrado na borda com junção redonda."""

    def __init__(self, contornos, preench, traco, largura):
        self.preench, self.traco, self.meio = preench, traco, largura / 2
        self.arestas = []
        for c in contornos:
            for i in range(len(c)):
                a, b = c[i], c[(i + 1) % len(c)]
                if a != b:
                    self.arestas.append((a, b))
        # balde de arestas por célula de 1 unidade, para o teste de distância do traço
        self.baldes = {}
        m = self.meio
        for e in self.arestas:
            (x1, y1), (x2, y2) = e
            for cx in range(math.floor(min(x1, x2) - m), math.floor(max(x1, x2) + m) + 1):
                for cy in range(math.floor(min(y1, y2) - m), math.floor(max(y1, y2) + m) + 1):
                    self.baldes.setdefault((cx, cy), []).append(e)
        self.cruzamentos = []

    def preparar_linha(self, py):
        """Cruzamentos das arestas com a horizontal py, em ordem de x, com o sentido (+1 ou -1)."""
        cr = []
        for (x1, y1), (x2, y2) in self.arestas:
            if (y1 <= py < y2) or (y2 <= py < y1):
                cr.append((x1 + (py - y1) * (x2 - x1) / (y2 - y1), 1 if y2 > y1 else -1))
        cr.sort()
        self.cruzamentos = cr

    def dentro(self, px):
        w = 0
        for x, s in self.cruzamentos:
            if x >= px:
                break
            w += s
        return w != 0

    def no_traco(self, px, py):
        m2 = self.meio * self.meio
        for (x1, y1), (x2, y2) in self.baldes.get((math.floor(px), math.floor(py)), ()):
            vx, vy = x2 - x1, y2 - y1
            t = min(max(((px - x1) * vx + (py - y1) * vy) / (vx * vx + vy * vy), 0), 1)
            dx, dy = x1 + t * vx - px, y1 + t * vy - py
            if dx * dx + dy * dy <= m2:
                return True
        return False

    def tinta_em(self, px, py):
        # traço por cima do preenchimento, como no SVG
        if self.traco and self.meio and self.no_traco(px, py):
            return self.traco
        if self.preench and self.dentro(px):
            return self.preench
        return None


def cor_em(tinta, px, py):
    if len(tinta) == 3:
        return tinta
    x1, y1, x2, y2, c0, c1 = tinta
    vx, vy = x2 - x1, y2 - y1
    s = min(max(((px - x1) * vx + (py - y1) * vy) / (vx * vx + vy * vy), 0), 1)
    return tuple(a + (b - a) * s for a, b in zip(c0, c1))


# ---------------------------------------------------------------- rasterização e arquivos

def rasterizar(caminho, lado_px, amostras=8):
    lado, formas = ler_svg(caminho)
    escala = lado / lado_px
    passo = 1 / amostras
    linhas = []
    for j in range(lado_px):
        soma = [[0.0, 0.0, 0.0, 0] for _ in range(lado_px)]
        for sj in range(amostras):
            py = (j + (sj + 0.5) * passo) * escala
            for f in formas:
                f.preparar_linha(py)
            for i in range(lado_px):
                acc = soma[i]
                for si in range(amostras):
                    px = (i + (si + 0.5) * passo) * escala
                    # todas as tintas são opacas: vale a última forma que cobre o ponto
                    for f in reversed(formas):
                        t = f.tinta_em(px, py)
                        if t is not None:
                            c = cor_em(t, px, py)
                            acc[0] += c[0]
                            acc[1] += c[1]
                            acc[2] += c[2]
                            acc[3] += 1
                            break
        linha = bytearray([0])  # filtro PNG "nenhum"
        for r, g, b, n in soma:
            if n:
                linha += bytes((round(r / n), round(g / n), round(b / n), round(255 * n / amostras ** 2)))
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
    if len(sys.argv) > 1:
        saida = conferencia = (RAIZ / sys.argv[1]).resolve()
    else:
        saida, conferencia = RAIZ / "static" / "favicon", RAIZ / "favicon"
    principal = saida / "favicon.svg"
    p16 = rasterizar(conferencia / "favicon-16.svg", 16)
    p32 = rasterizar(principal, 32)
    p48 = rasterizar(principal, 48)
    (saida / "favicon-32.png").write_bytes(p32)
    (saida / "apple-touch-icon.png").write_bytes(rasterizar(conferencia / "apple-touch-icon.svg", 180, amostras=4))
    (saida / "favicon.ico").write_bytes(ico([(16, p16), (32, p32), (48, p48)]))
    (conferencia / "favicon-16.png").write_bytes(p16)  # só para conferir o desenho de 16 px
    print(f"ok: {saida.relative_to(RAIZ)}: favicon-32.png, apple-touch-icon.png, favicon.ico (16, 32, 48)")


if __name__ == "__main__":
    main()
