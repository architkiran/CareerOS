// Refresh actual server state with a bounded, non-overlapping local poll.
(function () {
  "use strict";
  var target = document.querySelector("[data-mission-live]");
  var status = document.querySelector("[data-mission-live-status]");
  if (!target) return;
  var url = target.getAttribute("data-mission-live");
  var timer;
  async function refresh() {
    if (document.hidden || target.contains(document.activeElement)) {
      timer = setTimeout(refresh, 5000);
      return;
    }
    var controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, 8000);
    try {
      var response = await fetch(url, { credentials: "same-origin", signal: controller.signal });
      if (!response.ok) throw new Error("refresh failed");
      var html = await response.text();
      // Escaped, same-origin server-rendered fragment only.
      target.innerHTML = html;
      status.textContent = "Connected · local state refreshes every 5 seconds";
    } catch (error) {
      status.textContent = "Connection interrupted · showing last known state; retrying…";
    } finally {
      clearTimeout(timeout);
      timer = setTimeout(refresh, 5000);
    }
  }
  timer = setTimeout(refresh, 100);
  window.addEventListener("pagehide", function () { clearTimeout(timer); });
})();
