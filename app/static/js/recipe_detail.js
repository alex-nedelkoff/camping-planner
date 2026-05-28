/* Recipe detail: servings stepper rescales the ingredient quantities live.
   Ingredients carry their base qty in data-qty (empty if none) and a unit
   string in data-unit; we just multiply by current/base. */
(function () {
  "use strict";
  var article = document.querySelector(".rcp");
  if (!article) return;
  var base = parseInt(article.dataset.baseServings || "0", 10);
  if (!base || base < 1) return;
  var nEl = article.querySelector(".rcp-servings__n");
  var current = parseInt(nEl.dataset.currentServings || base, 10);
  var ings = article.querySelectorAll(".rcp-ing");

  function fmt(n) {
    if (n == null || isNaN(n)) return "";
    var rounded = Math.round(n * 100) / 100;
    // strip trailing .0 / trailing zeros, leaving e.g. 0.5, 1, 1.25
    return (rounded % 1 === 0) ? String(rounded)
                               : String(rounded).replace(/(\.\d*?)0+$/, "$1");
  }

  function render() {
    var ratio = current / base;
    nEl.textContent = current;
    nEl.dataset.currentServings = current;
    ings.forEach(function (li) {
      var qty = parseFloat(li.dataset.qty);
      var unit = li.dataset.unit || "";
      var span = li.querySelector(".rcp-ing__qty");
      if (isNaN(qty)) {
        span.textContent = unit ? unit : "";
      } else {
        var scaled = fmt(qty * ratio);
        span.textContent = unit ? (scaled + " " + unit) : scaled;
      }
    });
  }

  article.querySelectorAll(".rcp-step").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var delta = parseInt(btn.dataset.delta || "0", 10);
      current = Math.max(1, current + delta);
      render();
    });
  });
})();
