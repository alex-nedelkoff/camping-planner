/* Foods DB page (master-detail). Mounted by index.js when the route is /foods. */
(function (global) {
  'use strict';

  function mount(root) {
    const tpl = document.getElementById('tpl-foods');
    if (!tpl) return;
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    // Detail/list wiring is added in Tasks 10-11.
    document.getElementById('foods-detail').innerHTML =
      '<div class="empty">Select a food on the left, or click "+ Add food".</div>';
  }

  global.FoodsPage = { mount };
}(window));
