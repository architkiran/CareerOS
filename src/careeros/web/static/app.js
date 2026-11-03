// Live activity feed: Server-Sent Events with a polling fallback.
// Plain JS, no build step. All event text is inserted with textContent (never as HTML).
(function () {
  "use strict";
  var feed = document.querySelector("[data-live-feed]");
  if (!feed) return;
  var statusEl = document.querySelector("[data-live-status]");
  var statsEl = document.querySelector("[data-live-stats]");
  var cursor = parseInt(feed.getAttribute("data-cursor") || "0", 10) || 0;
  var refreshTimer = null;
  var pollTimer = null;
  var MAX_ITEMS = 50;
  var REFRESH_TYPES = /^(job\.|run\.|source\.|task\.)/;

  function setStatus(text) { if (statusEl) statusEl.textContent = text; }

  function refreshStats() {
    if (!statsEl) return;
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(function () {
      fetch("/partials/overview", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (html) { if (html !== null) statsEl.innerHTML = html; })  // server-rendered, escaped
        .catch(function () {});
    }, 400);
  }

  function add(ev) {
    if (!ev || typeof ev.id !== "number" || ev.id <= cursor) return;
    cursor = ev.id;
    var empty = document.querySelector("[data-live-empty]");
    if (empty) empty.remove();
    var li = document.createElement("li");
    li.className = "fresh";
    var time = document.createElement("time");
    time.textContent = ev.created_local || "";
    var code = document.createElement("code");
    code.textContent = ev.event_type || "";
    li.appendChild(time);
    li.appendChild(document.createTextNode(" "));
    li.appendChild(code);
    li.appendChild(document.createTextNode(" " + (ev.message || "")));
    feed.insertBefore(li, feed.firstChild);
    while (feed.children.length > MAX_ITEMS) feed.removeChild(feed.lastChild);
    if (REFRESH_TYPES.test(ev.event_type || "")) refreshStats();
  }

  function poll() {
    if (pollTimer) return;
    setStatus("Live (polling)");
    pollTimer = setInterval(function () {
      fetch("/events/feed?after=" + cursor, { credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (data) { (data.events || []).forEach(add); setStatus("Live (polling)"); })
        .catch(function () { setStatus("Offline, retrying…"); });
    }, 5000);
  }

  if (!("EventSource" in window)) { poll(); return; }
  var failures = 0;
  var es = new EventSource("/events/stream?after=" + cursor);
  es.addEventListener("activity", function (e) {
    try { add(JSON.parse(e.data)); } catch (err) { /* ignore malformed */ }
  });
  es.onopen = function () { failures = 0; setStatus("Live"); };
  es.onerror = function () {
    failures += 1;
    setStatus("Reconnecting…");
    if (failures >= 3) { es.close(); poll(); }
  };
})();
