/**
 * Linux Operations Portal – Client-side JavaScript
 * Foundation phase: initialise Bootstrap tooltips & dismiss alerts.
 * Additional interactive features will be added per module.
 */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    // ── Bootstrap tooltips ───────────────────────────────
    const tooltipEls = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipEls.forEach(function (el) {
      new bootstrap.Tooltip(el);
    });

    // ── Bootstrap popovers ──────────────────────────────
    const popoverEls = document.querySelectorAll('[data-bs-toggle="popover"]');
    popoverEls.forEach(function (el) {
      new bootstrap.Popover(el);
    });

    // ── Auto-dismiss flash messages after 5 seconds ─────
    const alerts = document.querySelectorAll(".alert.alert-dismissible");
    alerts.forEach(function (alert) {
      setTimeout(function () {
        const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
        if (bsAlert) bsAlert.close();
      }, 5000);
    });

    console.info("[LOP] Portal initialised.");
  });
})();
