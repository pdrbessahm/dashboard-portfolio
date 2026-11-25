"""Variações em degradê do favicon "pb" em JetBrains Mono (a fonte escolhida em favicon/opcoes.py).

    .venv/bin/python favicon/degrade.py
    node favicon/gerar.mjs <chrome>   (PNG e ICO do site, em static/favicon/)
    node favicon/gerar.mjs <chrome> static/favicon/opcoes/3-jetbrains-mono/degrade/<variação>   (PNG e ICO de uma variação)

Usa o mesmo desenho de favicon/opcoes.py (letras em contorno, 16 px preso à grade) e só troca as cores.
Cores do tema vitrine (tema-vitrine.css): gradiente dos botões #3d5af1 -> #7c4dff, fundo da capa #0f1d3a.

  a-fundo     fundo no degradê dos botões, em diagonal (azul no canto de cima à esquerda, lilás no de baixo
              à direita), "pb" branco. Branco sobre as duas pontas acima de 4,8:1.
  b-texto     fundo azul-marinho liso, "pb" inteiro num degradê diagonal do azul ao lilás (clareados para o
              fundo escuro). No 16 px o degradê vai de ponta a ponta do monograma, então ainda aparece.
  c-marinho   como o atual (p branco, b em azul e lilás), com o fundo num degradê suave do marinho ao índigo.

Saída em static/favicon/opcoes/3-jetbrains-mono/degrade/<variação>/ (favicon.svg, favicon-16.svg e
apple-touch-icon.svg). A pasta opcoes/ não vai para o site (o build pula).

A variação em ESCOLHIDA é o favicon do site: o script grava também o favicon.svg dela em static/favicon/
e os desenhos de 16 px e do iPhone em favicon/. Depois, node favicon/gerar.mjs <chrome> (sem pasta)
refaz favicon-32.png, apple-touch-icon.png e favicon.ico (16, 32 e 48 px) em static/favicon/.
"""

from opcoes import CONFERENCIA, ESCOLHIDA as FONTE, OPCOES, RAIZ, SAIDA, SITE, montar, num

OP = next(o for o in OPCOES if o["slug"] == FONTE)
DESTINO = SAIDA / OP["slug"] / "degrade"

# escolha do Pedro em 25/11/2026: a variação a na intensidade forte (a3), no lugar da intenso (a4)
ESCOLHIDA = "a3-forte"

MARINHO = "#0f1d3a"
INDIGO = "#2e2a7a"  # ponta escura do fundo da variação c: o marinho puxado para o lilás
AZUL = "#3d5af1"  # --acento-escuro
LILAS = "#7c4dff"  # --lilas
AZUL_CLARO = "#8fa3ff"  # o azul clareado para fundo escuro (mesmo do favicon atual)
LILAS_CLARO = "#c0a6ff"
BRANCO = "#ffffff"

VARIACOES = {
    "a-fundo": dict(fundo=(AZUL, LILAS), p=BRANCO, b=BRANCO),
    # a mesma variação a com a troca de cor mais perceptível: azul mais escuro e saturado numa ponta,
    # lilás mais quente (puxando para o rosa) na outra. Contraste do branco sobre cada ponta entre parênteses.
    "a2-acentuado": dict(fundo=("#2a44e8", "#9a4dff"), p=BRANCO, b=BRANCO),  # 6,8:1 e 4,3:1
    "a3-forte": dict(fundo=("#1f35c9", "#b04ef5"), p=BRANCO, b=BRANCO),  # 8,7:1 e 4,0:1
    "a4-intenso": dict(fundo=("#16249e", "#d94fd8"), p=BRANCO, b=BRANCO),  # 11,8:1 e 3,5:1
    "b-texto": dict(fundo=MARINHO, p="texto", b="texto"),
    "c-marinho": dict(fundo=(MARINHO, INDIGO), p=BRANCO, b="b"),
}


def gradiente(id_, x1, y1, x2, y2, c0, c1):
    return (f'    <linearGradient id="{id_}" gradientUnits="userSpaceOnUse" x1="{num(x1)}" y1="{num(y1)}" '
            f'x2="{num(x2)}" y2="{num(y2)}">\n'
            f'      <stop offset="0" stop-color="{c0}"/>\n'
            f'      <stop offset="1" stop-color="{c1}"/>\n'
            "    </linearGradient>")


def svg(var, lado, raio, margem, reforco, prender, comentario, fator=1.0):
    dp, db, (bx0, by0, bx1, by1), reforco = montar(OP, lado, margem, reforco, prender, fator)
    defs = []
    fundo = var["fundo"]
    if isinstance(fundo, tuple):
        # diagonal do canto de cima à esquerda ao de baixo à direita
        defs.append(gradiente("f", 0, 0, lado, lado, *fundo))
        fundo = "url(#f)"
    cores = {}
    for letra in "pb":
        cor = var[letra]
        if cor == "texto":
            # um degradê só para o monograma inteiro, do pé do p (baixo à esquerda) ao topo do b (cima à direita)
            if "t" not in cores:
                defs.append(gradiente("t", margem, lado - margem, lado - margem, margem, AZUL_CLARO, LILAS_CLARO))
            cor = cores["t"] = "url(#t)"
        elif cor == "b":
            # o do favicon atual: só na caixa do b
            defs.append(gradiente("g", bx0, by1, bx1, by0, AZUL_CLARO, LILAS_CLARO))
            cor = "url(#g)"
        cores[letra] = cor

    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}">', f"  <!-- {comentario} -->"]
    if defs:
        partes += ["  <defs>", *defs, "  </defs>"]
    raio_attr = f' rx="{num(raio)}"' if raio else ""
    partes.append(f'  <rect width="{lado}" height="{lado}"{raio_attr} fill="{fundo}"/>')
    for d, cor in ((dp, cores["p"]), (db, cores["b"])):
        traco = f' stroke="{cor}" stroke-width="{num(reforco)}" stroke-linejoin="round"' if reforco else ""
        partes.append(f'  <path d="{d}" fill="{cor}"{traco}/>')
    partes += ["</svg>", ""]
    return "\n".join(partes)


def main():
    base = 'Monograma "pb" em JetBrains Mono (SIL Open Font License), letras convertidas em contorno.'
    for slug, var in VARIACOES.items():
        pasta = DESTINO / slug
        pasta.mkdir(parents=True, exist_ok=True)
        rotulo = f" Variação em degradê {slug}. Gerado por favicon/degrade.py."
        (pasta / "favicon.svg").write_text(
            svg(var, 32, 7, OP["margem32"], OP["reforco32"], False, base + rotulo), encoding="utf-8")
        (pasta / "favicon-16.svg").write_text(
            svg(var, 16, 3.5, OP["margem16"], 0, True, base + " Desenho de 16 px." + rotulo), encoding="utf-8")
        (pasta / "apple-touch-icon.svg").write_text(
            svg(var, 32, 0, OP["margem32"], OP["reforco32"], False, base + " Tela inicial do iPhone." + rotulo,
                fator=0.8), encoding="utf-8")
        print(f"ok: {pasta.relative_to(RAIZ)}")
        if slug == ESCOLHIDA:
            for nome, destino in (("favicon.svg", SITE), ("favicon-16.svg", CONFERENCIA),
                                  ("apple-touch-icon.svg", CONFERENCIA)):
                (destino / nome).write_text((pasta / nome).read_text(encoding="utf-8"), encoding="utf-8")
            print(f"favicon do site: variação {slug} em static/favicon/favicon.svg e favicon/*.svg")


if __name__ == "__main__":
    main()
