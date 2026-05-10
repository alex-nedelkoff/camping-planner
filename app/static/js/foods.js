/* Foods DB page (master-detail). */
(function (global) {
  'use strict';

  let state = {
    catalog: { categories: [], foods: [] },
    selectedId: null,
    query: '',
    category: '',
    dirty: false,
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function fetchCatalog() {
    const r = await fetch('/api/foods');
    if (!r.ok) throw new Error('failed to load /api/foods');
    return r.json();
  }

  function renderCategoryFilter() {
    const sel = document.getElementById('foods-category-filter');
    sel.innerHTML = '<option value="">All categories</option>'
      + state.catalog.categories.map(c => `<option value="${c}">${c}</option>`).join('');
    sel.value = state.category;
  }

  function filteredFoods() {
    const q = state.query.toLowerCase().trim();
    return state.catalog.foods.filter(f => {
      if (state.category && f.category !== state.category) return false;
      if (q && !f.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function renderList() {
    const ul = document.getElementById('foods-list');
    const items = filteredFoods();
    if (!items.length) {
      ul.innerHTML = '<li style="cursor:default;color:#999">No matches.</li>';
      return;
    }
    ul.innerHTML = items.map(f =>
      `<li data-id="${escapeHtml(f.id)}"${state.selectedId === f.id ? ' class="selected"' : ''}>`
      + `${escapeHtml(f.name)}<span class="cat-tag">${escapeHtml(f.category)}</span>`
      + `</li>`
    ).join('');
    ul.querySelectorAll('li[data-id]').forEach(li => {
      li.addEventListener('click', () => {
        if (state.dirty && !confirm('Discard unsaved changes?')) return;
        state.selectedId = li.dataset.id;
        state.dirty = false;
        renderList();
        renderDetail();
      });
    });
  }

  function renderDetail() {
    // Real detail form added in Task 11. For now, just show a placeholder.
    const el = document.getElementById('foods-detail');
    if (!state.selectedId) {
      el.innerHTML = '<div class="empty">Select a food on the left, or click "+ Add food".</div>';
      return;
    }
    const food = state.catalog.foods.find(f => f.id === state.selectedId);
    el.innerHTML = `<pre>${escapeHtml(JSON.stringify(food, null, 2))}</pre>`;
  }

  async function mount(root) {
    const tpl = document.getElementById('tpl-foods');
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    state = { catalog: { categories: [], foods: [] }, selectedId: null, query: '', category: '', dirty: false };
    state.catalog = await fetchCatalog();
    renderCategoryFilter();
    renderList();
    renderDetail();
    document.getElementById('foods-search').addEventListener('input', (e) => {
      state.query = e.target.value;
      renderList();
    });
    document.getElementById('foods-category-filter').addEventListener('change', (e) => {
      state.category = e.target.value;
      renderList();
    });
    document.getElementById('foods-add').addEventListener('click', () => {
      if (state.dirty && !confirm('Discard unsaved changes?')) return;
      state.selectedId = '__new__';
      state.dirty = true;
      renderList();
      renderDetail();
    });
  }

  global.FoodsPage = { mount };
}(window));
