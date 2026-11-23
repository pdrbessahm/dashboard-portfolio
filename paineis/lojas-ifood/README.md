# Dashboard de BI das lojas iFood (versão anonimizada)

Painel web com vendas, pedidos, funil, itens e mudanças de cardápio de 13 lojas de restaurante no iFood.
Esta pasta tem só o HTML anonimizado do painel, para o portfólio.
O código do pipeline e do painel interno não está aqui.

## O que tem nesta pasta

- `painel.html`: o painel anonimizado, com os mesmos filtros e gráficos da versão interna.
  O plotly.js embutido foi trocado pelo que o site serve em `/static/vendor/plotly.min.js`.

No site, o painel fica em `/projetos/bi-lojas-ifood/painel/`, com uma barra de volta ao estudo de caso.

## O que o painel mostra

- KPIs do período escolhido: faturamento, pedidos, ticket médio, novos clientes e conversão, cada um contra o período anterior.
- Faturamento, pedidos e ticket médio por mês.
- Pedidos por dia, com os dias de mudança no cardápio marcados e a lista do que mudou.
- Antes e depois de cada dia com mudança no cardápio.
- Itens mais vendidos, menos vendidos e sem venda.
- Funil de visitas a pedidos.
- Todas as lojas no mesmo período, com variação contra a mesma janela do mês anterior.

## Anonimização

- As lojas aparecem só como Loja A a Loja M, com a letra sorteada uma vez.
  A ligação com a loja real fica fora do repositório.
- Os valores em R$ (faturamento, ticket médio e receita dos itens) são multiplicados por um fator fixo e sigiloso por loja.
  Tendências e variações percentuais continuam iguais às reais.
- Pedidos, novos clientes, funil e itens vendidos ficam reais.
- Por causa do fator, valores em R$ não se comparam entre lojas, e o rodapé do painel avisa.
- Os itens aparecem só como tipo e número (por exemplo Combo 01) e as mudanças no cardápio são descritas sem nomes próprios nem preços.
- As letras não batem com as do projeto Dados de lojas de delivery.

## Como atualizar

O painel chega pronto e anonimizado do projeto de origem e entra pelo comando abaixo, que troca o plotly.js e recusa o arquivo se achar dado sensível:

```
.venv/bin/python site.py importar-painel <painel anonimizado.html> lojas-ifood
```

Depois, `site.py build` publica o painel e `site.py verificar` confere de novo o `dist/`.
