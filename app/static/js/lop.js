/**
 * Linux Operations Portal – Client-side JavaScript
 * Handles: tooltips, popovers, toast notifications, loading overlay,
 *          UTC → local-timezone date display, relative time.
 */
(function () {
  "use strict";

  // ── Date/time helpers ────────────────────────────────────────────────────

  /**
   * Return a locale date string in the browser's local timezone.
   * Falls back to YYYY-MM-DD if Intl is unavailable.
   */
  function localDateStr(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    try {
      return d.toLocaleDateString(undefined, {
        year: "numeric", month: "2-digit", day: "2-digit",
      });
    } catch (_) {
      var y = d.getFullYear();
      var m = String(d.getMonth() + 1).padStart(2, "0");
      var day = String(d.getDate()).padStart(2, "0");
      return y + "-" + m + "-" + day;
    }
  }

  /** Return a human-readable relative time string ("3 days ago", etc.). */
  function relativeTime(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return "";
    var diffMs   = Date.now() - d.getTime();
    var diffDays = Math.round(diffMs / 86400000);
    if (diffDays <= 0)  return "today";
    if (diffDays === 1) return "yesterday";
    if (diffDays < 30)  return diffDays + " days ago";
    if (diffDays < 60)  return "1 month ago";
    if (diffDays < 365) return Math.round(diffDays / 30) + " months ago";
    var yrs = Math.round(diffDays / 365);
    return yrs + " year" + (yrs > 1 ? "s" : "") + " ago";
  }

  /**
   * Apply UTC → local-timezone conversion to every element that carries a
   * [data-utc] attribute.  If [data-relative] is also set, a "(N days ago)"
   * line is appended below the date.
   *
   * Existing `title` attributes are updated to the full local datetime string.
   */
  function applyLocalDates() {
    document.querySelectorAll("[data-utc]").forEach(function (el) {
      var iso = el.getAttribute("data-utc");
      if (!iso) return;

      var d = new Date(iso);
      if (isNaN(d)) return;

      var dateStr = localDateStr(iso);

      if (el.getAttribute("data-relative") === "true") {
        var rel = relativeTime(iso);
        el.innerHTML =
          dateStr +
          (rel
            ? '<br><span style="font-size:.72rem;color:var(--lop-muted);">(' + rel + ")</span>"
            : "");
      } else {
        el.textContent = dateStr;
      }

      // Update tooltip/title to full local datetime
      el.title = d.toLocaleString(undefined, {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
    });
  }

  // ── Main initialisation ──────────────────────────────────────────────────

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

    // ── UTC → local date display ─────────────────────────
    applyLocalDates();

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
