"""Mede os glifos p e b das fontes candidatas (unidades da fonte): caixa e largura da haste do p."""
import sys
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.pointInsidePen import PointInsidePen

for caminho in sys.argv[1:]:
    f = TTFont(caminho)
    gs = f.getGlyphSet()
    cmap = f.getBestCmap()
    print(caminho, "upm", f["head"].unitsPerEm)
    for ch in "pb":
        nome = cmap[ord(ch)]
        bp = BoundsPen(gs)
        gs[nome].draw(bp)
        x0, y0, x1, y1 = bp.bounds
        # haste: na altura do meio da descendente (p) ou da ascendente (b)
        y = y0 / 2 if ch == "p" else (y1 + y1 * 0.7) / 2
        dentro = []
        for x in range(int(x0), int(x1)):
            pen = PointInsidePen(gs, (x + 0.5, y))
            gs[nome].draw(pen)
            dentro.append(pen.getResult())
        ini = dentro.index(True)
        fim = dentro.index(False, ini)
        print(" ", ch, "caixa", bp.bounds, "haste", int(x0) + ini, "a", int(x0) + fim, "=", fim - ini)
