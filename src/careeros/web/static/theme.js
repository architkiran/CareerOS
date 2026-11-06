(function () {
  "use strict";
  var root = document.documentElement;
  try {
    root.dataset.theme = localStorage.getItem("careeros-theme") === "dark" ? "dark" : "light";
  } catch (error) { root.dataset.theme = "light"; }
  document.addEventListener("DOMContentLoaded", function () {
    var button = document.querySelector("[data-theme-toggle]");
    if (!button) return;
    function label() {
      button.textContent = root.dataset.theme === "light" ? "Switch to dark mode" : "Switch to light mode";
    }
    label();
    button.addEventListener("click", function () {
      root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
      try { localStorage.setItem("careeros-theme", root.dataset.theme); } catch (error) { /* optional */ }
      label();
    });
  });
})();
