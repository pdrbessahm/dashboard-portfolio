-- CTE: primeiro a variação de pedidos e de ticket de cada mês, depois a conta em cima dela
WITH mes_a_mes AS (
    SELECT loja,
           mes,
           idx_pedidos / LAG(idx_pedidos) OVER mes_anterior - 1 AS vp,
           idx_ticket / LAG(idx_ticket) OVER mes_anterior - 1 AS vt
    FROM vendas_mes
    WINDOW mes_anterior AS (PARTITION BY loja ORDER BY mes_num)
)
SELECT loja,
       mes,
       -- faturamento = pedidos x ticket; cada efeito usa a média do outro fator nos dois meses,
       -- e os dois somam exatamente a variação do faturamento
       ROUND(100 * vp * (2 + vt) / 2, 1) AS efeito_pedidos,
       ROUND(100 * vt * (2 + vp) / 2, 1) AS efeito_ticket,
       ROUND(100 * ((1 + vp) * (1 + vt) - 1), 1) AS var_faturamento
FROM mes_a_mes
WHERE mes = 'set' AND loja IN ('Loja A', 'Loja B', 'Loja C')
ORDER BY loja;
