WITH acumulado AS (
    SELECT loja,
           item,
           pct,
           -- soma acumulada: do item que mais vende para o que menos vende, dentro de cada loja
           SUM(pct) OVER (PARTITION BY loja ORDER BY pct DESC, linha
                          ROWS UNBOUNDED PRECEDING) AS pct_acumulado
    FROM itens_mes
)
SELECT a.loja,
       -- classe A: o item entra se, antes dele, a soma ainda não tinha chegado a 80%
       COUNT(*) FILTER (WHERE a.pct_acumulado - a.pct < 80) AS itens_classe_a,
       c.itens_no_cardapio,
       ROUND(100.0 * COUNT(*) FILTER (WHERE a.pct_acumulado - a.pct < 80) / c.itens_no_cardapio) AS pct_do_cardapio
FROM acumulado AS a
-- o cardápio inteiro, com os itens sem venda, vem de outra tabela
JOIN cardapio AS c ON c.loja = a.loja
GROUP BY a.loja, c.itens_no_cardapio
ORDER BY pct_do_cardapio;
