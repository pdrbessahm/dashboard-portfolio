"""Gera dados/itens.json (curva ABC) a partir do painel já anonimizado das lojas iFood.

    .venv/bin/python anonimizacao/itens.py

A fonte é paineis/lojas-ifood/painel.html, que já saiu anonimizado do projeto de origem: lojas com letra
sorteada (as do painel, não as do dados-delivery), itens como tipo e número e receita multiplicada por um
fator fixo por loja. Aqui só sai a participação de cada item na receita da loja no mês, que o fator não muda.
Só entra out de 2026: é o primeiro mês em que o painel traz também os itens sem venda, o cardápio inteiro.
"""
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FONTE = RAIZ / "paineis" / "lojas-ifood" / "painel.html"
SAIDA = RAIZ / "dados" / "itens.json"
PERIODO = "20261001_20261031"
# mesma regra do resto do site: loja com menos de 50 pedidos no mês não sustenta conclusão
MIN_PEDIDOS = 50
DADOS_PAINEL = re.compile(r"(\{\"lojas\".*)")


def dados_painel():
    for linha in FONTE.read_text(encoding="utf-8").splitlines():
        achado = DADOS_PAINEL.search(linha)
        if achado:
            return json.JSONDecoder().raw_decode(achado.group(1))[0]
    raise SystemExit("Não achei os dados embutidos no painel: o formato mudou, confira antes.")


def main():
    d = dados_painel()
    pedidos = {x["loja_id"]: x["pedidos"] for x in d["desempenho"] if x["periodo_id"] == PERIODO}
    lojas = []
    for loja in sorted({i["loja_id"] for i in d["itens"] if i["periodo_id"] == PERIODO}):
        if pedidos.get(loja, 0) < MIN_PEDIDOS:
            continue
        itens = [i for i in d["itens"] if i["loja_id"] == loja and i["periodo_id"] == PERIODO]
        total = sum(i["receita"] or 0 for i in itens)
        vendidos = sorted((i for i in itens if i["quantidade"]), key=lambda i: -(i["receita"] or 0))
        lojas.append({
            "loja": loja,
            "itens_no_cardapio": len(itens),
            "itens": [{"item": i["item_nome"], "pct": round(100 * i["receita"] / total, 2)} for i in vendidos],
        })
    saida = {"fonte": "painel anonimizado das lojas iFood, out de 2026; letras do painel", "mes": "out", "lojas": lojas}
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"gravado {SAIDA.relative_to(RAIZ)}: {len(lojas)} lojas")


if __name__ == "__main__":
    main()
