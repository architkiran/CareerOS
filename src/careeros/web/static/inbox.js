/* Direct links always work without JavaScript; local telemetry never redirects them. */
(function () {
  "use strict";
  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[data-job-open]");
    if (!link || !navigator.sendBeacon) return;
    var token = document.querySelector("[data-open-csrf]");
    if (!token) return;
    var form = new FormData(); form.append("csrf_token", token.value);
    navigator.sendBeacon("/inbox/jobs/" + encodeURIComponent(link.dataset.jobOpen) + "/opened", form);
  });
  async function refresh() {
    var region = document.querySelector("[data-core-inbox]");
    if (!region || document.hidden || region.contains(document.activeElement) || region.querySelector("details[open]")) return;
    try {
      var response = await fetch(region.dataset.partialUrl, {credentials:"same-origin", cache:"no-store"});
      if (response.ok) { var text = await response.text(); region.innerHTML = text; }
    } catch (_) { /* Keep the previous observations and their timestamps visible. */ }
  }
  window.setInterval(refresh, 20000);
})();
