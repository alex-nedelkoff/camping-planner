/* Foods DB page (master-detail). */
(function (global) {
  'use strict';

  let state = {
    catalog: { categories: [], foods: [] },
    selectedId: null,
    query: '',
    category: '',
    draft: null,        // current edit buffer when a row is selected
    dirty: false,
    error: '',
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
        select(li.dataset.id);
      });
    });
  }

  function select(id) {
    state.selectedId = id;
    state.error = '';
    if (id === '__new__') {
      state.draft = { id: '', name: '', category: state.catalog.categories[0] || 'other',
                      kcal_per_serving: 0, serving_size: '', url: '' };
      state.dirty = true;
    } else {
      const food = state.catalog.foods.find(f => f.id === id);
      state.draft = food ? { ...food } : null;
      state.dirty = false;
    }
    renderList();
    renderDetail();
  }

  function bindDraftField(field, type) {
    return (e) => {
      let v = e.target.value;
      if (type === 'int') v = parseInt(v, 10) || 0;
      state.draft[field] = v;
      state.dirty = true;
    };
  }

  function renderDetail() {
    const el = document.getElementById('foods-detail');
    if (!state.draft) {
      el.innerHTML = '<div class="empty">Select a food on the left, or click "+ Add food".</div>';
      return;
    }
    const d = state.draft;
    const isNew = state.selectedId === '__new__';
    const catOpts = state.catalog.categories
      .map(c => `<option value="${c}"${c === d.category ? ' selected' : ''}>${c}</option>`).join('');
    const errBanner = state.error
      ? `<div class="error-banner">${escapeHtml(state.error)}</div>` : '';
    el.innerHTML = `
      ${errBanner}
      <label>Name
        <input type="text" id="fd-name" value="${escapeHtml(d.name)}">
      </label>
      <label>Category
        <select id="fd-category">${catOpts}</select>
      </label>
      <label>kcal per serving
        <input type="number" id="fd-kcal" min="0" step="1" value="${d.kcal_per_serving || 0}">
      </label>
      <label>Serving size
        <input type="text" id="fd-serving" value="${escapeHtml(d.serving_size || '')}">
      </label>
      <label>URL (optional)
        <div class="url-row">
          <input type="url" id="fd-url" value="${escapeHtml(d.url || '')}" placeholder="https://...">
          ${d.url ? `<a href="${escapeHtml(d.url)}" target="_blank" rel="noopener">open ↗</a>` : ''}
        </div>
      </label>
      <div class="actions">
        <button class="btn" id="fd-save">${isNew ? 'Create' : 'Save'}</button>
        ${isNew ? '' : '<button class="btn danger" id="fd-delete">× Delete</button>'}
      </div>
    `;
    document.getElementById('fd-name').addEventListener('input', bindDraftField('name'));
    document.getElementById('fd-category').addEventListener('change', bindDraftField('category'));
    document.getElementById('fd-kcal').addEventListener('input', bindDraftField('kcal_per_serving', 'int'));
    document.getElementById('fd-serving').addEventListener('input', bindDraftField('serving_size'));
    document.getElementById('fd-url').addEventListener('input', bindDraftField('url'));
    document.getElementById('fd-save').addEventListener('click', save);
    if (!isNew) document.getElementById('fd-delete').addEventListener('click', () => del(d.id));
  }

  async function save() {
    state.error = '';
    const d = state.draft;
    const isNew = state.selectedId === '__new__';
    const payload = {
      name: d.name,
      category: d.category,
      kcal_per_serving: d.kcal_per_serving,
      serving_size: d.serving_size,
      url: d.url || null,
    };
    try {
      let res;
      if (isNew) {
        res = await fetch('/api/foods', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch(`/api/foods/${encodeURIComponent(d.id)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        state.error = (j.detail && j.detail.error) || `HTTP ${res.status}`;
        renderDetail();
        return;
      }
      const newId = isNew ? (await res.json()).id : d.id;
      state.catalog = await fetchCatalog();
      state.dirty = false;
      select(newId);
    } catch (err) {
      state.error = String(err);
      renderDetail();
    }
  }

  async function del(id) {
    if (!confirm(`Delete "${state.draft.name}"?`)) return;
    let res = await fetch(`/api/foods/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (res.status === 409) {
      const j = await res.json();
      const refs = (j.detail && j.detail.references) || [];
      const msg = `This food is used by ${refs.length} trip(s):\n  ${refs.join('\n  ')}\n\nDelete anyway?`;
      if (!confirm(msg)) return;
      res = await fetch(`/api/foods/${encodeURIComponent(id)}?force=true`, { method: 'DELETE' });
    }
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      state.error = (j.detail && j.detail.error) || `HTTP ${res.status}`;
      renderDetail();
      return;
    }
    state.catalog = await fetchCatalog();
    state.selectedId = null;
    state.draft = null;
    state.dirty = false;
    renderList();
    renderDetail();
  }

  async function mount(root) {
    const tpl = document.getElementById('tpl-foods');
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    state = { catalog: { categories: [], foods: [] }, selectedId: null,
              query: '', category: '', draft: null, dirty: false, error: '' };
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
      select('__new__');
    });
  }

  global.FoodsPage = { mount };
}(window));
