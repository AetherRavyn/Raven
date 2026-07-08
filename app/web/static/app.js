// RAVEN FRIDAY-level dashboard — keyboard shortcuts, global search,
// error boundaries, onboarding wizard, live status, active nav.

(function () {
  "use strict";

  // ── Helpers ────────────────────────────────────────────────────
  function $(id) { return document.getElementById(id); }
  function qs(sel) { return document.querySelector(sel); }
  function qsa(sel) { return document.querySelectorAll(sel); }

  // ── Error Boundaries ──────────────────────────────────────────
  function initErrorBoundaries() {
    // Global JS error handler
    window.addEventListener("error", function (e) {
      console.error("[Raven Error]", e.message, e.filename, e.lineno);
      showToast("Script error: " + (e.message || "unknown"), "error");
    });
    // Unhandled promise rejections
    window.addEventListener("unhandledrejection", function (e) {
      console.error("[Raven Unhandled]", e.reason);
    });
  }

  // ── Toast System ───────────────────────────────────────────────
  var toastContainer = null;

  function ensureToastContainer() {
    if (!toastContainer) {
      toastContainer = document.createElement("div");
      toastContainer.id = "raven-toast-container";
      toastContainer.style.cssText =
        "position:fixed;bottom:1rem;right:1rem;z-index:9999;display:flex;flex-direction:column;gap:0.5rem;max-width:24rem;";
      document.body.appendChild(toastContainer);
    }
    return toastContainer;
  }

  function showToast(message, type, duration) {
    type = type || "info";
    duration = duration || 5000;
    var container = ensureToastContainer();
    var toast = document.createElement("div");
    var bg = type === "error" ? "var(--error)" : type === "success" ? "var(--success)" : "var(--accent)";
    toast.style.cssText =
      "padding:0.5rem 0.75rem;border-radius:0.375rem;font-size:12px;color:#fff;background:" + bg +
      ";box-shadow:0 4px 12px rgba(0,0,0,0.3);animation:fadeIn 0.2s ease-out;";
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(function () {
      toast.style.opacity = "0";
      toast.style.transition = "opacity 0.3s";
      setTimeout(function () { toast.remove(); }, 300);
    }, duration);
  }

  // ── Keyboard Shortcuts ─────────────────────────────────────────
  function initKeyboardShortcuts() {
    var buffer = "";
    var bufferTimer = null;

    document.addEventListener("keydown", function (e) {
      // Don't capture when typing in inputs/textarea
      var tag = e.target && e.target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
        if (e.key === "Escape") {
          e.target.blur();
          return;
        }
        return;
      }

      // Single-key shortcuts
      switch (e.key) {
        case "?":
          e.preventDefault();
          toggleHelpOverlay();
          return;
        case "/":
          e.preventDefault();
          focusSearch();
          return;
        case "Escape":
          closeOverlay();
          return;
      }

      // Multi-key chord (g + key)
      if (e.key === "g") {
        buffer = "g";
        clearTimeout(bufferTimer);
        bufferTimer = setTimeout(function () { buffer = ""; }, 800);
        return;
      }
      if (buffer === "g") {
        buffer = "";
        var nav = {
          "h": "/", "c": "/chat", "s": "/sessions",
          "k": "/kanban", "b": "/blueprints", "l": "/logs",
          "m": "/models", "p": "/providers", "o": "/cowork",
        };
        var target = nav[e.key];
        if (target) {
          e.preventDefault();
          navigateTo(target);
        }
        return;
      }
    });
  }

  // ── Help Overlay ───────────────────────────────────────────────
  var helpOverlay = null;

  function toggleHelpOverlay() {
    if (helpOverlay && helpOverlay.style.display !== "none") {
      helpOverlay.style.display = "none";
      return;
    }
    if (!helpOverlay) {
      helpOverlay = document.createElement("div");
      helpOverlay.id = "raven-help-overlay";
      helpOverlay.style.cssText =
        "position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;";
      helpOverlay.addEventListener("click", function (e) {
        if (e.target === helpOverlay) helpOverlay.style.display = "none";
      });
      var box = document.createElement("div");
      box.style.cssText =
        "background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:0.5rem;padding:1.5rem;max-width:32rem;width:90%;max-height:80vh;overflow:auto;";
      box.innerHTML =
        '<h2 class="text-sm font-semibold mb-3" style="color:var(--accent);">Keyboard Shortcuts</h2>' +
        '<div class="space-y-2 text-[12px]">' +
          shortcutRow("?", "Show this help") +
          shortcutRow("/", "Focus search bar") +
          shortcutRow("Escape", "Close overlay") +
          shortcutRow("g then h", "Go to Home") +
          shortcutRow("g then c", "Go to Chat") +
          shortcutRow("g then s", "Go to Sessions") +
          shortcutRow("g then k", "Go to Kanban") +
          shortcutRow("g then b", "Go to Blueprints") +
          shortcutRow("g then l", "Go to Logs") +
          shortcutRow("g then m", "Go to Models") +
          shortcutRow("g then p", "Go to Providers") +
          shortcutRow("g then o", "Go to Cowork") +
        '</div>';
      helpOverlay.appendChild(box);
      document.body.appendChild(helpOverlay);
    }
    helpOverlay.style.display = "flex";
  }

  function shortcutRow(key, desc) {
    return '<div class="flex items-center justify-between py-1">' +
      '<kbd style="background:var(--bg-primary);border:1px solid var(--border-color);border-radius:3px;padding:1px 6px;font-family:JetBrains Mono,monospace;font-size:11px;color:var(--accent);">' + key + '</kbd>' +
      '<span style="color:var(--text-secondary);">' + desc + '</span>' +
    '</div>';
  }

  // ── Global Search ──────────────────────────────────────────────
  var searchOverlay = null;
  var searchInput = null;

  function initSearch() {
    // Add search trigger button to header if not already present
    var headerRight = qs("header .flex.items-center.gap-3");
    if (!headerRight) return;

    // Check if already exists
    if ($("raven-search-trigger")) return;

    var btn = document.createElement("button");
    btn.id = "raven-search-trigger";
    btn.textContent = "\u2318/";
    btn.style.cssText =
      "font-size:11px;padding:2px 8px;border:1px solid var(--border-color);border-radius:4px;color:var(--text-muted);cursor:pointer;background:transparent;";
    btn.title = "Search (/)";
    btn.addEventListener("click", focusSearch);

    var pill = $("status-pill");
    if (pill) {
      headerRight.insertBefore(btn, pill);
    } else {
      headerRight.appendChild(btn);
    }
  }

  function focusSearch() {
    if (!searchOverlay) buildSearchOverlay();
    searchOverlay.style.display = "flex";
    setTimeout(function () {
      if (searchInput) searchInput.focus();
    }, 100);
  }

  function buildSearchOverlay() {
    searchOverlay = document.createElement("div");
    searchOverlay.id = "raven-search-overlay";
    searchOverlay.style.cssText =
      "position:fixed;inset:0;z-index:9997;background:rgba(0,0,0,0.5);display:none;align-items:flex-start;justify-content:center;padding-top:15vh;";
    searchOverlay.addEventListener("click", function (e) {
      if (e.target === searchOverlay) closeOverlay();
    });

    var box = document.createElement("div");
    box.style.cssText =
      "background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:0.5rem;padding:1rem;width:90%;max-width:36rem;max-height:50vh;display:flex;flex-direction:column;";

    searchInput = document.createElement("input");
    searchInput.type = "text";
    searchInput.placeholder = "Search sessions, memory, knowledge\u2026";
    searchInput.style.cssText =
      "width:100%;background:var(--bg-primary);border:1px solid var(--border-color);border-radius:4px;padding:0.5rem 0.75rem;font-size:13px;color:var(--text-primary);outline:none;";
    searchInput.addEventListener("input", debounce(function () { doSearch(searchInput.value); }, 300));
    searchInput.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { closeOverlay(); }
      if (e.key === "Enter") { doSearch(searchInput.value); }
    });
    box.appendChild(searchInput);

    var results = document.createElement("div");
    results.id = "raven-search-results";
    results.style.cssText = "margin-top:0.75rem;overflow-y:auto;flex:1;";
    box.appendChild(results);

    searchOverlay.appendChild(box);
    document.body.appendChild(searchOverlay);

    window.__ravenSearchResults = results;
  }

  function doSearch(query) {
    var el = $("raven-search-results");
    if (!el) return;
    if (!query || query.length < 2) {
      el.innerHTML = '<div class="text-zinc-600 text-[12px] p-2">Type at least 2 characters to search.</div>';
      return;
    }
    el.innerHTML = '<div class="text-zinc-500 text-[12px] p-2">Searching\u2026</div>';
    fetch("/api/search?q=" + encodeURIComponent(query) + "&limit=10")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.results || data.results.length === 0) {
          el.innerHTML = '<div class="text-zinc-600 text-[12px] p-2">No results for "' + query + '"</div>';
          return;
        }
        var html = '<div class="text-zinc-500 text-[10px] uppercase mb-1">' + data.count + ' results</div>';
        data.results.forEach(function (r) {
          html +=
            '<a href="' + r.url + '" class="block px-2 py-1.5 rounded hover:bg-ink-700 transition-colors text-[12px]" style="color:var(--text-secondary);">' +
              '<span class="text-zinc-500 text-[10px] uppercase mr-2">[' + r.type + ']</span>' +
              '<span>' + escapeHtml(r.label) + '</span>' +
            '</a>';
        });
        el.innerHTML = html;
      })
      .catch(function () {
        el.innerHTML = '<div class="text-zinc-600 text-[12px] p-2">Search failed. Try again.</div>';
      });
  }

  // ── Onboarding Wizard ──────────────────────────────────────────
  var onboardingOverlay = null;
  var onboardingStep = 0;
  var onboardingSteps = [
    { title: "Welcome to Raven", body: "Your personal AI agent is ready. Let\u2019s get you set up in 3 quick steps." },
    { title: "Configure Provider", body: "Set up an API key for your LLM provider to start chatting. Go to PROVIDERS to add your keys." },
    { title: "Connect a Channel", body: "Talk to Raven from Telegram, Discord, or WhatsApp. Go to CHANNELS to connect." },
    { title: "All Set!", body: "You\u2019re ready. Try typing a message in CHAT or explore the dashboard." },
  ];

  function initOnboarding() {
    var onboarded = localStorage.getItem("raven_onboarded");
    if (onboarded === "true") return;

    // Check server-side onboarding status
    fetch("/api/onboarding/status")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.onboarded) {
          localStorage.setItem("raven_onboarded", "true");
          return;
        }
        // Show onboarding after a short delay
        setTimeout(showOnboarding, 500);
      })
      .catch(function () {
        // Offline — show onboarding anyway for first-time users
        if (!onboarded) setTimeout(showOnboarding, 500);
      });
  }

  function showOnboarding() {
    if (onboardingOverlay) {
      onboardingOverlay.style.display = "flex";
      return;
    }
    onboardingOverlay = document.createElement("div");
    onboardingOverlay.id = "raven-onboarding-overlay";
    onboardingOverlay.style.cssText =
      "position:fixed;inset:0;z-index:9996;background:rgba(0,0,0,0.7);display:flex;align-items:center;justify-content:center;";

    var box = document.createElement("div");
    box.style.cssText =
      "background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:0.75rem;padding:2rem;max-width:28rem;width:90%;text-align:center;";

    box.innerHTML =
      '<div id="onboarding-icon" class="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4 text-2xl" style="background:var(--accent);color:var(--bg-primary);">R</div>' +
      '<h2 id="onboarding-title" class="text-lg font-semibold mb-2" style="color:var(--text-primary);">' + onboardingSteps[0].title + '</h2>' +
      '<p id="onboarding-body" class="text-[13px] mb-6" style="color:var(--text-secondary);">' + onboardingSteps[0].body + '</p>' +
      '<div class="flex items-center justify-center gap-2 mb-4">' +
        '<span class="step-dot active w-2 h-2 rounded-full" style="background:var(--accent);"></span>' +
        '<span class="step-dot w-2 h-2 rounded-full" style="background:var(--border-color);"></span>' +
        '<span class="step-dot w-2 h-2 rounded-full" style="background:var(--border-color);"></span>' +
        '<span class="step-dot w-2 h-2 rounded-full" style="background:var(--border-color);"></span>' +
      '</div>' +
      '<div class="flex items-center justify-center gap-3">' +
        '<button id="onboarding-skip" class="px-4 py-2 text-[12px] border border-ink-600 rounded hover:bg-ink-700 transition-colors" style="color:var(--text-muted);">Skip</button>' +
        '<button id="onboarding-next" class="px-4 py-2 text-[12px] border rounded hover:opacity-90 transition-colors" style="background:var(--accent);color:var(--bg-primary);">Next</button>' +
      '</div>';

    onboardingOverlay.appendChild(box);
    document.body.appendChild(onboardingOverlay);

    var dots = onboardingOverlay.querySelectorAll(".step-dot");

    document.getElementById("onboarding-next").addEventListener("click", function () {
      onboardingStep++;
      if (onboardingStep >= onboardingSteps.length) {
        finishOnboarding();
        return;
      }
      document.getElementById("onboarding-title").textContent = onboardingSteps[onboardingStep].title;
      document.getElementById("onboarding-body").textContent = onboardingSteps[onboardingStep].body;
      dots.forEach(function (d, i) {
        d.style.background = i <= onboardingStep ? "var(--accent)" : "var(--border-color)";
      });
      if (onboardingStep === onboardingSteps.length - 1) {
        document.getElementById("onboarding-next").textContent = "Done";
      }
    });

    document.getElementById("onboarding-skip").addEventListener("click", finishOnboarding);
  }

  function finishOnboarding() {
    localStorage.setItem("raven_onboarded", "true");
    fetch("/api/onboarding/complete", { method: "POST" }).catch(function () {});
    if (onboardingOverlay) {
      onboardingOverlay.style.display = "none";
    }
    showToast("Welcome to Raven! Press ? for shortcuts.", "success", 4000);
  }

  // ── Navigation ─────────────────────────────────────────────────
  function navigateTo(path) {
    window.location.href = path;
  }

  function closeOverlay() {
    if (helpOverlay) helpOverlay.style.display = "none";
    if (searchOverlay) searchOverlay.style.display = "none";
  }

  // ── Active Sidebar Link ────────────────────────────────────────
  function initActiveNav() {
    var path = window.location.pathname;
    qsa("aside a[data-nav-slug]").forEach(function (a) {
      var slug = a.getAttribute("data-nav-slug");
      if (path === "/" + slug || path === "/" + slug + "/" ||
          path === "/page/" + slug || path === "/page/" + slug + "/") {
        a.classList.add("active");
      }
    });
  }

  // ── Status Pill ────────────────────────────────────────────────
  function initStatusPill() {
    var pill = $("status-pill");
    var sidebarDot = $("sidebar-online");

    function setPill(state) {
      if (!pill) return;
      if (state === "connected") {
        pill.textContent = "\u25CF live";
        pill.style.color = "var(--success)";
        if (sidebarDot) sidebarDot.style.background = "var(--success)";
      } else if (state === "connecting") {
        pill.textContent = "\u25CB connecting";
        pill.style.color = "var(--warning)";
        if (sidebarDot) sidebarDot.style.background = "var(--warning)";
      } else {
        pill.textContent = "\u25CB offline";
        pill.style.color = "var(--text-muted)";
        if (sidebarDot) sidebarDot.style.background = "var(--text-muted)";
      }
    }

    function checkStatus() {
      fetch("/api/system/status")
        .then(function (r) { return r.json(); })
        .then(function (data) {
          setPill(data && data.status === "running" ? "connected" : "offline");
        })
        .catch(function () { setPill("offline"); });
    }

    setPill("connecting");
    checkStatus();
    setInterval(checkStatus, 30000);

    window.__ravenDashboard = {
      setPill: setPill,
      checkStatus: checkStatus,
      focusSearch: focusSearch,
      showToast: showToast,
      showHelp: toggleHelpOverlay,
    };
  }

  // ── Utilities ──────────────────────────────────────────────────
  function debounce(fn, ms) {
    var timer;
    return function () {
      var ctx = this, args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  // ── Init ───────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", function () {
    initErrorBoundaries();
    initActiveNav();
    initStatusPill();
    initKeyboardShortcuts();
    initSearch();
    initOnboarding();
  });

  // Also run immediately if DOM is already loaded
  if (document.readyState === "complete" || document.readyState === "interactive") {
    initErrorBoundaries();
    setTimeout(function () {
      initActiveNav();
      initStatusPill();
      initKeyboardShortcuts();
      initSearch();
      initOnboarding();
    }, 0);
  }
})();
