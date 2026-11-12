// Today: list and detail, keyboard triage, instant save and dismiss, draft copying.
(function () {
  "use strict";
  var root = document.querySelector("[data-today]");
  if (!root) return;
  var toast = (window.CareerOS && window.CareerOS.toast) || function () {};
  var rows = Array.prototype.slice.call(root.querySelectorAll("[data-row]"));
  var cards = {};
  root.querySelectorAll("[data-card]").forEach(function (c) { cards[c.dataset.id] = c; });
  var tabs = Array.prototype.slice.call(root.querySelectorAll("[data-tab]"));
  var ink = root.querySelector("[data-ink]");
  var search = root.querySelector("[data-search-input]");
  var none = root.querySelector("[data-none]");
  var detail = root.querySelector("[data-detail]");
  var groups = Array.prototype.slice.call(root.querySelectorAll("[data-group]"));
  var olderBar = root.querySelector("[data-older-bar]");
  var olderCount = root.querySelector("[data-older-count]");
  var olderToggle = root.querySelector("[data-older-toggle]");
  var clock = root.querySelector("[data-clock]");
  var bucket = "eligible", current = null, showOlder = false;

  function visible() { return rows.filter(function (r) { return !r.hidden && r.isConnected; }); }
  function transition(fn) {
    if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.startViewTransition(fn);
    else fn();
  }
  function select(id, opts) {
    if (!cards[id] || id === current) return;
    var apply = function () {
      rows.forEach(function (r) { r.classList.toggle("is-active", r.dataset.id === id); });
      Object.keys(cards).forEach(function (k) { cards[k].classList.toggle("is-active", k === id); });
      current = id;
      detail.scrollTop = 0;
    };
    if (opts && opts.instant) apply(); else transition(apply);
    var row = rows.filter(function (r) { return r.dataset.id === id; })[0];
    if (row) {
      // Scroll only the list, never the page.
      var box = row.closest("[data-list]"), top = row.offsetTop - box.offsetTop;
      if (top < box.scrollTop) box.scrollTop = top - 8;
      else if (top + row.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = top + row.offsetHeight - box.clientHeight + 8;
    }
    history.replaceState(null, "", "#job-" + id);
  }
  function moveInk() {
    var on = tabs.filter(function (t) { return t.dataset.tab === bucket; })[0];
    if (on && ink) { ink.style.left = on.offsetLeft + "px"; ink.style.width = on.offsetWidth + "px"; }
  }
  function filter(keep) {
    var q = (search.value || "").trim().toLowerCase();
    var older = 0;
    rows.forEach(function (r) {
      var match = r.dataset.bucket === bucket && !(q && r.dataset.search.indexOf(q) === -1);
      if (match && r.dataset.fresh === "older") older += 1;
      // Roles older than 30 days stay folded away unless asked for or searched for.
      r.hidden = !match || (r.dataset.fresh === "older" && !showOlder && !q);
    });
    groups.forEach(function (g) {
      g.hidden = !rows.some(function (r) {
        return !r.hidden && r.isConnected && r.dataset.bucket === g.dataset.bucket && r.dataset.fresh === g.dataset.group;
      });
    });
    if (olderBar) {
      olderBar.hidden = older === 0 || Boolean(q);
      olderCount.textContent = older + (older === 1 ? " role" : " roles") + " older than 30 days";
      olderToggle.textContent = showOlder ? "Hide them" : "Show them";
    }
    var list = visible();
    none.hidden = list.length > 0;
    if (!list.length) {
      Object.keys(cards).forEach(function (k) { cards[k].classList.remove("is-active"); });
      current = null;
    } else if (!keep || !list.some(function (r) { return r.dataset.id === current; })) {
      current = null; select(list[0].dataset.id, { instant: true });
    }
  }
  function setBucket(name, keep) {
    bucket = name;
    tabs.forEach(function (t) { t.setAttribute("aria-selected", t.dataset.tab === name ? "true" : "false"); });
    moveInk(); filter(keep);
    try { sessionStorage.setItem("today-bucket", name); } catch (e) { /* optional */ }
  }
  function count(name, delta) {
    var tab = tabs.filter(function (t) { return t.dataset.tab === name; })[0];
    var b = tab && tab.querySelector("b");
    if (b) b.textContent = String(Math.max(parseInt(b.textContent, 10) + delta, 0));
  }
  function step(delta) {
    var list = visible();
    if (!list.length) return;
    var i = list.findIndex(function (r) { return r.dataset.id === current; });
    var next = list[Math.min(Math.max(i + delta, 0), list.length - 1)];
    select(next.dataset.id);
  }

  tabs.forEach(function (t) { t.addEventListener("click", function () { setBucket(t.dataset.tab); }); });
  rows.forEach(function (r) { r.addEventListener("click", function (e) { e.preventDefault(); select(r.dataset.id); root.classList.add("is-reading"); }); });
  root.querySelectorAll("[data-back]").forEach(function (b) { b.addEventListener("click", function () { root.classList.remove("is-reading"); }); });
  if (olderToggle) olderToggle.addEventListener("click", function () { showOlder = !showOlder; filter(true); });
  function tick() {
    if (!clock) return;
    var d = new Date();
    clock.textContent = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  tick(); setInterval(tick, 20000);
  // The board settles once on load; later filtering must not replay it.
  setTimeout(function () { root.classList.add("settled"); }, 900);
  search.addEventListener("input", function () { filter(true); });
  search.addEventListener("keydown", function (e) { if (e.key === "Escape") { search.value = ""; filter(true); search.blur(); } });
  window.addEventListener("resize", moveInk);
  window.addEventListener("load", moveInk);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(moveInk);
  document.addEventListener("careeros:select", function (e) {
    var row = rows.filter(function (r) { return r.dataset.id === e.detail; })[0];
    if (row) { search.value = ""; setBucket(row.dataset.bucket, true); select(row.dataset.id); }
  });

  // Save and dismiss without leaving the page; the server stays the source of truth.
  root.querySelectorAll("form[data-async]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var kind = form.dataset.async, card = form.closest("[data-card]"), id = card.dataset.id;
      var row = rows.filter(function (r) { return r.dataset.id === id; })[0];
      fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin" })
        .then(function (res) {
          if (!res.ok) throw new Error(String(res.status));
          if (kind === "save") {
            var done = document.createElement("span");
            done.className = "ui-btn ui-btn-quiet"; done.textContent = "Saved";
            form.replaceWith(done);
            if (row && !row.querySelector("[data-saved-mark]")) {
              var mark = document.createElement("span");
              mark.className = "td-mark"; mark.textContent = "Saved";
              row.querySelector(".meta").appendChild(mark);
            }
            toast("Saved");
          } else {
            var list = visible(), i = list.indexOf(row), next = list[i + 1] || list[i - 1];
            count(card.dataset.bucket, -1);
            if (row) {
              row.classList.add("leaving");
              setTimeout(function () { row.parentElement.remove(); rows = rows.filter(function (r) { return r !== row; }); if (!visible().length) none.hidden = false; }, 240);
            }
            delete cards[id];
            current = null;
            if (next) select(next.dataset.id); 
            card.remove();
            root.classList.remove("is-reading");
            filter(true);
            toast("Dismissed");
          }
        })
        .catch(function () { toast("That did not go through. Reload and try again."); });
    });
  });

  // Drafts: live character count and copy.
  root.querySelectorAll("[data-draft]").forEach(function (area) {
    var foot = area.parentElement.querySelector("[data-count]");
    var limit = parseInt(area.dataset.limit || "0", 10);
    function update() {
      var n = area.value.length;
      foot.textContent = limit ? n + " of " + limit + " characters" : n + " characters";
      foot.classList.toggle("over", Boolean(limit) && n > limit);
    }
    area.addEventListener("input", update); update();
    area.parentElement.querySelector("[data-copy]").addEventListener("click", function () {
      var done = function () { toast("Copied"); };
      if (navigator.clipboard) navigator.clipboard.writeText(area.value).then(done, function () { area.select(); document.execCommand("copy"); done(); });
      else { area.select(); document.execCommand("copy"); done(); }
    });
  });

  document.addEventListener("keydown", function (e) {
    var t = e.target;
    if (e.metaKey || e.ctrlKey || e.altKey || document.querySelector("dialog[open]")) return;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    var card = current && cards[current];
    if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); step(1); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); step(-1); }
    else if (e.key === "/") { e.preventDefault(); search.focus(); }
    else if (e.key === "1" || e.key === "2" || e.key === "3") { setBucket(["eligible", "research", "review"][Number(e.key) - 1]); }
    else if (!card) { return; }
    else if (e.key === "o" || e.key === "Enter") { e.preventDefault(); window.open(card.querySelector("[data-open]").href, "_blank", "noopener"); }
    else if (e.key === "s") { var s = card.querySelector('form[data-async="save"] button'); if (s) s.click(); }
    else if (e.key === "x") { var x = card.querySelector('form[data-async="dismiss"] button'); if (x) x.click(); }
  });

  var start = "eligible";
  var hash = (location.hash || "").replace("#job-", "");
  try { start = sessionStorage.getItem("today-bucket") || start; } catch (e) { /* optional */ }
  if (cards[hash]) start = cards[hash].dataset.bucket;
  else if (!rows.some(function (r) { return r.dataset.bucket === start; })) {
    start = ["eligible", "research", "review"].filter(function (b) { return rows.some(function (r) { return r.dataset.bucket === b; }); })[0] || "eligible";
  }
  setBucket(start);
  if (cards[hash]) { current = null; select(hash, { instant: true }); }
})();
