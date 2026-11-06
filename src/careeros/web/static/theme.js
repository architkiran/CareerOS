(function () {
  "use strict";
  var root = document.documentElement;
  try {
    if (localStorage.getItem("careeros-theme") === "light") root.dataset.theme = "light";
  } catch (error) { /* Storage may be disabled; dark remains the default. */ }
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
