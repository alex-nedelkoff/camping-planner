/* Gear DB page (master-detail). Mounted by index.js when route is /gear. */
(function (global) {
  'use strict';

  function mount(root) {
    const tpl = document.getElementById('tpl-gear');
    if (!tpl) return;
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    document.getElementById('gear-detail').innerHTML =
      '<div class="empty">Select an item on the left, or click "+ Add item".</div>';
  }

  global.GearPage = { mount };
}(window));
