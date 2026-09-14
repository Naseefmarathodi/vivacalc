/* VivaCalc — progressive enhancement only.
   Every page works with JavaScript disabled; this adds the mobile drawer,
   dismissible alerts and the live margin preview on the booking form. */
(function () {
  "use strict";

  // Signals to CSS that the JS drawer is available, which disables the
  // :target fallback below. Without JS the class is never added and the
  // pure-CSS fallback keeps navigation working.
  document.documentElement.classList.add("js");

  // --- Mobile navigation drawer -------------------------------------------
  var app = document.querySelector(".app");
  var toggle = document.querySelector("[data-nav-toggle]");
  var scrim = document.querySelector("[data-nav-scrim]");

  function closeNav() {
    if (!app) return;
    app.classList.remove("nav-open");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    if (location.hash === "#sidebar") {
      history.replaceState(null, "", location.pathname + location.search);
    }
  }

  if (toggle && app) {
    toggle.addEventListener("click", function (e) {
      // The control is an <a href="#sidebar"> so it works without JS; with JS
      // we take over and skip the hash navigation.
      e.preventDefault();
      var open = app.classList.toggle("nav-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  if (scrim) scrim.addEventListener("click", function (e) {
    e.preventDefault();
    closeNav();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeNav();
  });

  // --- Dismissible alerts --------------------------------------------------
  document.querySelectorAll("[data-dismiss]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var alert = btn.closest(".alert");
      if (alert) alert.remove();
    });
  });

  // --- Live margin preview on the booking form -----------------------------
  // Display only. The authoritative margin is always computed server-side.
  var buy = document.getElementById("id_buy_price");
  var sell = document.getElementById("id_sell_price");
  var out = document.querySelector("[data-margin-output]");

  if (buy && sell && out) {
    var row = out.closest(".row--total");
    var buyOut = document.querySelector("[data-buy-output]");
    var sellOut = document.querySelector("[data-sell-output]");

    var fmt = new Intl.NumberFormat(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });

    var update = function () {
      var b = parseFloat(buy.value);
      var s = parseFloat(sell.value);
      if (buyOut) buyOut.textContent = isNaN(b) ? "—" : fmt.format(b);
      if (sellOut) sellOut.textContent = isNaN(s) ? "—" : fmt.format(s);
      if (isNaN(b) || isNaN(s)) {
        out.textContent = "—";
        if (row) row.classList.remove("is-negative");
        return;
      }
      var m = s - b;
      out.textContent = fmt.format(m);
      if (row) row.classList.toggle("is-negative", m < 0);
    };

    buy.addEventListener("input", update);
    sell.addEventListener("input", update);
    update();
  }
})();
