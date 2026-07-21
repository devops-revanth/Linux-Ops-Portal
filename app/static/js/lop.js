/**
 * Linux Operations Portal – Client-side JavaScript
 * Handles: tooltips, popovers, toast notifications, loading overlay.
 */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {

    // ── Bootstrap tooltips ───────────────────────────────
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
      new bootstrap.Tooltip(el, { trigger: "hover" });
    });

    // ── Bootstrap popovers ──────────────────────────────
    document.querySelectorAll('[data-bs-toggle="popover"]').forEach(function (el) {
      new bootstrap.Popover(el);
    });

    // ── Toast notifications (flash messages) ─────────────
    document.querySelectorAll("#lop-toast-container .toast").forEach(function (el) {
      var t = new bootstrap.Toast(el, { autohide: true, delay: 5000 });
      t.show();
    });

    // ── Page loading overlay ─────────────────────────────
    var loader = document.getElementById("lop-loader");

    function showLoader() {
      if (loader) loader.classList.add("active");
    }

    function hideLoader() {
      if (loader) loader.classList.remove("active");
    }

    // Show on qualifying link clicks
    document.addEventListener("click", function (e) {
      var anchor = e.target.closest("a[href]");
      if (!anchor) return;

      var href = anchor.getAttribute("href");

      // Skip: empty, anchor-only, javascript:, new-tab, modal/tab/collapse triggers
      if (!href || href === "#" || href.startsWith("#") || href.startsWith("javascript")) return;
      if (anchor.target === "_blank") return;
      if (anchor.dataset.bsToggle) return;  // modal, tab, collapse, dropdown
      if (anchor.classList.contains("disabled")) return;

      // Skip modifier keys (open in new tab, etc.)
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;

      showLoader();
    });

    // Show on form submits (skip the instant-search filter form)
    document.addEventListener("submit", function (e) {
      var form = e.target;
      if (!form || form.dataset.noLoader === "true") return;
      if (form.id === "filter-form") return;  // instant search — no overlay
      showLoader();
    });

    // Hide if the browser restores a cached page (back/forward)
    window.addEventListener("pageshow", function (e) {
      if (e.persisted) hideLoader();
    });

    console.info("[LOP] Portal initialised.");
  });
})();
