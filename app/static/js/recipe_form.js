/* Dynamic ingredient rows on the recipe form: add/remove. Submission collects
   ing_qty[], ing_unit[], ing_name[] as parallel lists — the server drops any
   row whose name is blank. */
(function () {
  "use strict";
  var editor = document.querySelector(".rcp-ing-editor");
  if (!editor) return;
  var tbody = editor.querySelector("tbody");
  var addBtn = editor.querySelector(".rcp-row-add");

  function attachRemove(btn) {
    btn.addEventListener("click", function () {
      var rows = tbody.querySelectorAll(".rcp-ing-row");
      if (rows.length <= 1) {
        // never delete the last row — clear it instead so the user can keep typing
        btn.closest("tr").querySelectorAll("input").forEach(function (i) { i.value = ""; });
        return;
      }
      btn.closest("tr").remove();
    });
  }

  tbody.querySelectorAll(".rcp-row-remove").forEach(attachRemove);

  addBtn.addEventListener("click", function () {
    var template = tbody.querySelector(".rcp-ing-row");
    var row = template.cloneNode(true);
    row.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    attachRemove(row.querySelector(".rcp-row-remove"));
    tbody.appendChild(row);
    row.querySelector("input").focus();
  });
})();
