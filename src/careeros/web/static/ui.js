// CareerOS shell: command palette, go-to shortcuts, toasts. No dependencies, CSP-safe.
(function () {
  "use strict";
  document.documentElement.classList.add("js");
  var toasts = document.querySelector("[data-toasts]");
  function toast(message) {
    if (!toasts) return;
    var el = document.createElement("div");
    el.className = "ui-toast";
    el.textContent = message;
    toasts.appendChild(el);
    setTimeout(function () { el.classList.add("out"); }, 2200);
    setTimeout(function () { el.remove(); }, 2500);
  }
  window.CareerOS = { toast: toast };

  var palette = document.querySelector("[data-palette]");
  var help = document.querySelector("[data-help]");
  var input = palette && palette.querySelector("input");
  var list = palette && palette.querySelector("ul");
  var items = [], shown = [], index = 0;

  function collect() {
    items = [];
    document.querySelectorAll("a[data-cmd]").forEach(function (a) {
      items.push({ label: a.dataset.cmd, hint: "Page", run: function () { location.href = a.href; } });
    });
    document.querySelectorAll("[data-row]").forEach(function (row) {
      var title = row.querySelector("strong"), sub = row.querySelector(".sub");
      items.push({
        label: title ? title.textContent : "", hint: sub ? sub.textContent : "Role",
        run: function () { document.dispatchEvent(new CustomEvent("careeros:select", { detail: row.dataset.id })); }
      });
    });
    items.push({ label: "Keyboard shortcuts", hint: "Help", run: function () { help && help.showModal(); } });
    var theme = document.querySelector("[data-theme-toggle]");
    if (theme) items.push({ label: "Switch theme", hint: "Appearance", run: function () { theme.click(); } });
  }
  function render() {
    var q = input.value.trim().toLowerCase();
    shown = items.filter(function (i) { return !q || (i.label + " " + i.hint).toLowerCase().indexOf(q) !== -1; }).slice(0, 40);
    index = Math.min(index, Math.max(shown.length - 1, 0));
    list.textContent = "";
    shown.forEach(function (item, n) {
      var li = document.createElement("li"), small = document.createElement("small");
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", n === index ? "true" : "false");
      li.textContent = item.label;
      small.textContent = item.hint;
      li.appendChild(small);
      li.addEventListener("click", function () { palette.close(); item.run(); });
      list.appendChild(li);
    });
    var active = list.children[index];
    if (active) active.scrollIntoView({ block: "nearest" });
  }
  function openPalette() {
    if (!palette || palette.open) return;
    collect(); input.value = ""; index = 0; render(); palette.showModal(); input.focus();
  }
  if (palette) {
    input.addEventListener("input", function () { index = 0; render(); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { index = Math.min(index + 1, shown.length - 1); render(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { index = Math.max(index - 1, 0); render(); e.preventDefault(); }
      else if (e.key === "Enter" && shown[index]) { e.preventDefault(); palette.close(); shown[index].run(); }
    });
    palette.addEventListener("click", function (e) { if (e.target === palette) palette.close(); });
  }
  document.querySelectorAll("[data-open-palette]").forEach(function (b) { b.addEventListener("click", openPalette); });
  document.querySelectorAll("[data-open-help]").forEach(function (b) { b.addEventListener("click", function () { help && help.showModal(); }); });
  document.querySelectorAll("[data-autosubmit]").forEach(function (el) { el.addEventListener("change", function () { el.form.submit(); }); });

  var goPending = false;
  function typing(e) {
    var t = e.target;
    return t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  }
  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
    if (typing(e) || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("dialog[open]")) return;
    if (goPending) {
      goPending = false;
      var link = document.querySelector('[data-testid="workspace-nav"] a[data-key="' + e.key.toLowerCase() + '"]');
      if (link) { e.preventDefault(); location.href = link.href; }
      return;
    }
    if (e.key === "g") { goPending = true; setTimeout(function () { goPending = false; }, 900); }
    else if (e.key === "?") { e.preventDefault(); help && help.showModal(); }
  });
})();
