-- CTE com CASE: cada dia ganha o nome da janela a que pertence
WITH janelas AS (
    SELECT indice,
           CASE
               WHEN dia BETWEEN '2026-08-06' AND '2026-09-04' THEN '1. 06/08 a 04/09, antes'
               WHEN dia BETWEEN '2026-09-05' AND '2026-09-13' THEN '2. 05 a 13/09, depois da reordenação'
               WHEN dia BETWEEN '2026-09-15' AND '2026-09-30' THEN '3. 15 a 30/09'
           END AS janela
    FROM pedidos_dia
    -- dia sem pedido é dia fechado: fica fora da média, em vez de entrar como zero
    WHERE loja = 'Loja B' AND indice IS NOT NULL
)
SELECT janela,
       COUNT(*) AS dias_abertos,
       ROUND(AVG(indice), 1) AS pedidos_por_dia
FROM janelas
WHERE janela IS NOT NULL
GROUP BY janela
ORDER BY janela;
