// Open a collapsed <details> section when the URL points at it (e.g. /jobs/x#lane-123),
// so the thing you just saved is visible. Plain JS, no inline code (CSP-safe).
(function () {
  "use strict";
  function reveal() {
    var id = decodeURIComponent((location.hash || "").slice(1));
    if (!id) return;
    var el = document.getElementById(id);
    if (!el) return;
    var node = el;
    while (node) {
      if (node.tagName === "DETAILS") node.open = true;
      node = node.parentElement;
    }
    el.scrollIntoView({ block: "start" });
  }
  window.addEventListener("hashchange", reveal);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", reveal);
  else reveal();
})();
