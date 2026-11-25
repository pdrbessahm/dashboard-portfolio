// Topo da página inicial da vitrine: transparente sobre a foto, sólido depois de rolar um pouco.
(function () {
  var topo = document.querySelector(".topo-heroi");
  if (!topo) return;
  function atualizar() {
    topo.classList.toggle("rolado", window.scrollY > 24);
  }
  atualizar();
  window.addEventListener("scroll", atualizar, { passive: true });
})();
