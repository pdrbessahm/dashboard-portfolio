SELECT l.loja,
       l.segmento,
       v.mes,
       ROUND(100 * (v.idx_faturamento / LAG(v.idx_faturamento) OVER mes_anterior - 1), 1) AS var_faturamento,
       ROUND(100 * (v.idx_pedidos / LAG(v.idx_pedidos) OVER mes_anterior - 1), 1) AS var_pedidos
FROM vendas_mes AS v
-- o segmento mora na tabela de lojas; o JOIN traz para cada linha de venda
JOIN lojas AS l ON l.loja = v.loja
WHERE l.loja = 'Loja B'
-- LAG olha a linha anterior dentro da mesma loja, na ordem dos meses: mês cheio contra mês cheio
WINDOW mes_anterior AS (PARTITION BY v.loja ORDER BY v.mes_num)
ORDER BY v.mes_num;
