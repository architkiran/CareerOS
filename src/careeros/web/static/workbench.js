"use strict";
(() => {
  const panel = document.querySelector("[data-rewrite-pending]");
  if (!panel) return;
  let edited = false;
  document.querySelector(".resume-editor")?.addEventListener("input", () => { edited = true; });
  const check = async () => {
    try {
      const response = await fetch(panel.dataset.rewritePending, {cache: "no-store"});
      if (!response.ok) return;
      const state = await response.json();
      if (["queued", "running"].includes(state.status)) return;
      clearInterval(timer);
      if (!edited) { window.location.reload(); return; }
      const notice = document.createElement("p");
      notice.setAttribute("role", "status");
      notice.textContent = "The rewrite finished. Refresh after saving your current edits to review its result.";
      panel.prepend(notice);
    } catch (_) { /* A stopped local app is recoverable with a refresh. */ }
  };
  const timer = setInterval(check, 3000);
})();
