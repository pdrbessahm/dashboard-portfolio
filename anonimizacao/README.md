# Anonimização

Os scripts desta pasta leem os projetos de origem só para leitura e gravam em `../dados/` apenas JSON já anonimizado e agregado.

- `lojas.py` gera `dados/lojas.json` a partir dos fechamentos mensais das lojas.
  O de-para (letra, loja de origem, meses) e o caminho da origem ficam em `$PORTFOLIO_PRIVADO/lojas.toml`, fora do repositório.
  A saída não tem nome, id nem valor absoluto: só índice (primeiro mês da loja = 100), porcentagem e participação.

```
PORTFOLIO_PRIVADO=<pasta privada> .venv/bin/python anonimizacao/lojas.py
PORTFOLIO_PRIVADO=<pasta privada> .venv/bin/python site.py verificar
```
