// RAVEN Hermes dashboard — frontend glue
//
// Responsibilities:
//   1. Mark the active sidebar link based on the URL path
//   2. Show system status in the top-right status pill
//   3. Auto-refresh status periodically
//   4. Theme persistence

(function () {
  "use strict";

  // ── Active sidebar link ──────────────────────────────────────
  var path = window.location.pathname;
  document.querySelectorAll("aside a[data-nav-slug]").forEach(function (a) {
    var slug = a.getAttribute("data-nav-slug");
    if (path === "/" + slug || path === "/" + slug + "/" ||
        path === "/page/" + slug || path === "/page/" + slug + "/") {
      a.classList.add("active");
    }
  });

  // ── Status pill ──────────────────────────────────────────────
  var pill = document.getElementById("status-pill");
  var sidebarDot = document.getElementById("sidebar-online");

  function setPill(state) {
    if (!pill) return;
    if (state === "connected") {
      pill.textContent = "● live";
      pill.style.color = "var(--success)";
      if (sidebarDot) sidebarDot.style.background = "var(--success)";
    } else if (state === "connecting") {
      pill.textContent = "○ connecting";
      pill.style.color = "var(--warning)";
      if (sidebarDot) sidebarDot.style.background = "var(--warning)";
    } else {
      pill.textContent = "○ offline";
      pill.style.color = "var(--text-muted)";
      if (sidebarDot) sidebarDot.style.background = "var(--text-muted)";
    }
  }

  function checkStatus() {
    fetch("/api/system/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.status === "running") {
          setPill("connected");
        } else {
          setPill("offline");
        }
      })
      .catch(function () {
        setPill("offline");
      });
  }

  // Check status on load and every 30 seconds
  setPill("connecting");
  checkStatus();
  setInterval(checkStatus, 30000);

  // Expose for other scripts
  window.__ravenDashboard = {
    setPill: setPill,
    checkStatus: checkStatus,
  };
})();
