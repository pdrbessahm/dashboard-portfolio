"""Gera dados/lojas.json a partir dos fechamentos mensais das lojas, só lendo a origem.

    PORTFOLIO_PRIVADO=<pasta privada> .venv/bin/python anonimizacao/lojas.py

O de-para (letra, loja de origem e meses), o caminho da origem e o desenho dos arquivos
dela ficam em $PORTFOLIO_PRIVADO/lojas.toml, fora do repositório. A saída não tem nome, id nem valor
absoluto: só índice (primeiro mês da loja = 100), porcentagem e participação.
"""
import json
import os
import sys
import tomllib
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "dados" / "lojas.json"

MESES = {"06": "jun", "07": "jul", "08": "ago", "09": "set", "10": "out"}
DIAS = {"monday": "seg", "tuesday": "ter", "wednesday": "qua", "thursday": "qui",
        "friday": "sex", "saturday": "sáb", "sunday": "dom"}
# a plataforma separa em 9 tipos; no site ficam 5 grupos
PAGAMENTO = {"pix": "Pix", "credit": "Crédito", "debit": "Débito", "digital_wallet": "Carteira digital",
             "cash": "Dinheiro", "meal_voucher": "Vale-refeição", "voucher": "Vale-refeição", "other_voucher": "Vale-refeição"}
# datas das mudanças de vitrine da Loja B marcadas no gráfico do caso
EVENTOS_CASO = [("2026-08-06", "mudança de 06/08"), ("2026-09-05", "reordenação de 05/09")]


def pasta_privada():
    pasta = os.environ.get("PORTFOLIO_PRIVADO")
    if not pasta or not (Path(pasta) / "lojas.toml").exists():
        sys.exit("defina PORTFOLIO_PRIVADO apontando para a pasta com lojas.toml")
    return Path(pasta)


def fechamento(cfg, slug, mes):
    """O fechamento do mês fica na pasta do próprio mês; o de jun só existe na de jul."""
    for pasta in (mes, f"{int(mes) + 1:02d}"):
        arq = Path(cfg["fonte"]) / cfg["fechamento"].format(pasta=pasta, slug=slug, mes=mes)
        if arq.exists():
            d = json.loads(arq.read_text(encoding="utf-8"))
            if d.get("_erros"):
                sys.exit(f"{arq.name}: fechamento com erro de captura, não uso")
            if d["inicio"] != f"2026-{mes}-01":
                sys.exit(f"{arq.name}: mês incompleto ({d['inicio']} a {d['fim']})")
            return d
    sys.exit(f"sem fechamento de {slug} em {mes}")


def pct(parte, todo):
    return round(100 * parte / todo, 1) if todo else None


def participacao(itens, grupos=None):
    total = sum(i["value"] for i in itens)
    soma = {}
    for i in itens:
        chave = grupos.get(i["key"], "Outros") if grupos is not None else DIAS[i["key"]]
        soma[chave] = soma.get(chave, 0) + i["value"]
    return {k: pct(v, total) for k, v in soma.items()}


def variacao(atual, anterior):
    return round(100 * (atual / anterior - 1), 1) if anterior else None


def loja(cfg, letra, c):
    meses = [(m, fechamento(cfg, c["slug"], m)) for m in c["meses"]]
    base = meses[0][1]["kpis"]
    serie, anterior = [], None
    for mes, d in meses:
        k = d["kpis"]
        visitas = d["funil"][0]["value"]
        valores = {"faturamento": k["faturamento"]["value"], "pedidos": k["pedidos"]["value"],
                   "ticket": k["ticket"]["value"]}
        linha = {
            "mes": MESES[mes],
            "indice": {n: round(100 * v / base[n]["value"], 1) for n, v in valores.items()},
            "conversao": round(100 * k["conversao"]["atual"], 1),
            "funil": [{"etapa": e["label"], "pct": pct(e["value"], visitas)} for e in d["funil"]],
            "disponibilidade": round(100 * d["disponibilidade"]["pct"], 1),
            "dias": participacao(d["dias"]),
            "pagamento": participacao(d["pagamento"], PAGAMENTO),
        }
        # comparação calculada aqui, mês cheio contra mês cheio (a "var" do painel usa outra janela)
        if anterior:
            linha["variacao"] = {n: variacao(v, anterior[n]) for n, v in valores.items()}
            linha["variacao"]["conversao_pp"] = round(linha["conversao"] - anterior["conversao"], 1)
        serie.append(linha)
        anterior = {**valores, "conversao": linha["conversao"]}
    saida = {"loja": f"Loja {letra}", "segmento": c.get("segmento"), "meses": serie}
    if c.get("apoio"):
        saida["apoio"] = c["apoio"]
    return saida


def caso_loja_b(cfg, slug):
    """Pedidos por dia aberto em ago e set, em índice (média de ago por dia aberto = 100).

    Dia sem pedido conta como dia fechado: a loja não fica aberta um dia inteiro sem vender.
    """
    serie = json.loads((Path(cfg["fonte"]) / cfg["serie_diaria"]).read_text(encoding="utf-8"))[slug]
    dias = {**serie["08"], **serie["09"]}
    abertos_ago = [v for d, v in serie["08"].items() if v > 0]
    base = sum(abertos_ago) / len(abertos_ago)
    pontos = [{"dia": d, "dia_semana": list(DIAS.values())[date.fromisoformat(d).weekday()],
               "indice": round(100 * v / base, 1) if v > 0 else None}
              for d, v in sorted(dias.items())]
    return {"loja": "Loja B", "base": "média de ago por dia aberto = 100", "pontos": pontos,
            "eventos": [{"dia": d, "rotulo": r} for d, r in EVENTOS_CASO]}


def main():
    privado = pasta_privada()
    cfg = tomllib.loads((privado / "lojas.toml").read_text(encoding="utf-8"))
    lojas = [loja(cfg, letra, c) for letra, c in cfg["lojas"].items()]
    dados = {
        "fonte": "fechamentos mensais do painel da plataforma, jun a out de 2026",
        "lojas": lojas,
        "caso_loja_b": caso_loja_b(cfg, cfg["lojas"]["B"]["slug"]),
    }
    SAIDA.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"gravado {SAIDA.relative_to(RAIZ)}: {len(lojas)} lojas, "
          f"{sum(len(l['meses']) for l in lojas)} meses")


if __name__ == "__main__":
    main()
