// Landing: keep the board clock current.
(function () {
  "use strict";
  var clock = document.querySelector(".ld [data-clock]");
  if (!clock) return;
  function tick() {
    var d = new Date();
    clock.textContent = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  tick(); setInterval(tick, 20000);
})();
