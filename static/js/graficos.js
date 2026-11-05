// Desenha as figuras montadas em Python (site.py) e gravadas como JSON na página.
// Gráfico com versão estreita troca de versão quando a área cruza ESTREITO px.
// layout.meta.seletor vira um <select> acima do gráfico; cada opção liga só os traços dela.
(function () {
  var ESTREITO = 560;
  var config = { responsive: true, displaylogo: false,
                 modeBarButtonsToRemove: ["select2d", "lasso2d"] };
  var areas = [];

  function montarSeletor(area, seletor) {
    var rotulo = document.createElement("label");
    rotulo.className = "grafico-seletor";
    rotulo.textContent = seletor.nome + " ";
    var select = document.createElement("select");
    var grupos = {};
    seletor.opcoes.forEach(function (o, i) {
      var opcao = new Option(o.rotulo, String(i));
      if (o.grupo) {
        if (!grupos[o.grupo]) {
          grupos[o.grupo] = document.createElement("optgroup");
          grupos[o.grupo].label = o.grupo;
          select.appendChild(grupos[o.grupo]);
        }
        grupos[o.grupo].appendChild(opcao);
      } else {
        select.appendChild(opcao);
      }
    });
    select.value = String(seletor.ativo);
    select.addEventListener("change", function () {
      area.dataset.opcao = select.value;
      aplicar(area);
    });
    rotulo.appendChild(select);
    area.parentNode.insertBefore(rotulo, area);
  }

  function aplicar(area) {
    var seletor = area.layout && area.layout.meta && area.layout.meta.seletor;
    if (!seletor || area.dataset.opcao === undefined) return;
    Plotly.restyle(area, { visible: seletor.opcoes[Number(area.dataset.opcao)].visivel });
  }

  function desenhar(area) {
    var estreita = area.dataset.figuraEstreita && area.clientWidth < ESTREITO;
    var id = estreita ? area.dataset.figuraEstreita : area.dataset.figura;
    if (area.dataset.desenhada === id) return;
    var fonte = document.getElementById(id);
    if (!fonte) return;
    var figura = JSON.parse(fonte.textContent);
    var seletor = figura.layout.meta && figura.layout.meta.seletor;
    if (seletor && !area.dataset.desenhada) montarSeletor(area, seletor);
    area.dataset.desenhada = id;
    // a versão trocada mantém a opção escolhida
    Plotly.react(area, figura.data, figura.layout, config).then(function () { aplicar(area); });
  }

  document.querySelectorAll("[data-figura]").forEach(function (area) {
    areas.push(area);
    desenhar(area);
  });

  var espera;
  window.addEventListener("resize", function () {
    clearTimeout(espera);
    espera = setTimeout(function () { areas.forEach(desenhar); }, 150);
  });
})();
