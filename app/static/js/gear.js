/* Gear DB page (master-detail). */
(function (global) {
  'use strict';

  let state = {
    catalog: { categories: [], items: [] },
    selectedId: null,
    query: '',
    category: '',
    draft: null,
    weightUnknown: false,
    dirty: false,
    error: '',
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // Deterministic colour for a category — same colour everywhere across reloads.
  function pillColor(category) {
    const palette = ['#2563eb', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed',
                     '#0891b2', '#db2777', '#65a30d', '#ea580c', '#475569',
                     '#9333ea', '#0d9488'];
    let h = 0;
    for (let i = 0; i < category.length; i++) h = (h * 31 + category.charCodeAt(i)) >>> 0;
    return palette[h % palette.length];
  }

  function renderCategoryPill(category) {
    return `<span class="gear-pill" style="background:${pillColor(category)}">${escapeHtml(category)}</span>`;
  }

  async function fetchCatalog() {
    const r = await fetch('/api/gear');
    if (!r.ok) throw new Error('failed to load /api/gear');
    return r.json();
  }

  function renderCategoryFilter() {
    const sel = document.getElementById('gear-category-filter');
    sel.innerHTML = '<option value="">All categories</option>'
      + state.catalog.categories.map(c => `<option value="${c}">${c}</option>`).join('');
    sel.value = state.category;
  }

  function filteredItems() {
    const q = state.query.toLowerCase().trim();
    return state.catalog.items.filter(it => {
      if (state.category && it.category !== state.category) return false;
      if (q && !it.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function renderList() {
    const ul = document.getElementById('gear-list');
    const items = filteredItems();
    if (!items.length) {
      ul.innerHTML = '<li style="cursor:default;color:#999">No matches.</li>';
      return;
    }
    ul.innerHTML = items.map(it => {
      const wt = it.weight_g === null || it.weight_g === undefined
        ? '? g' : `${it.weight_g.toLocaleString()} g`;
      return `<li data-id="${escapeHtml(it.id)}"${state.selectedId === it.id ? ' class="selected"' : ''}>`
        + `<span class="gear-name">${escapeHtml(it.name)}</span>`
        + renderCategoryPill(it.category)
        + `<span class="gear-weight">${wt}</span>`
        + `</li>`;
    }).join('');
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
      state.draft = { id: '', name: '',
                      category: state.catalog.categories[0] || 'Other',
                      weight_g: 0 };
      state.weightUnknown = false;
      state.dirty = true;
    } else {
      const it = state.catalog.items.find(x => x.id === id);
      state.draft = it ? { ...it } : null;
      state.weightUnknown = it && it.weight_g === null;
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
    const el = document.getElementById('gear-detail');
    if (!state.draft) {
      el.innerHTML = '<div class="empty">Select an item on the left, or click "+ Add item".</div>';
      return;
    }
    const d = state.draft;
    const isNew = state.selectedId === '__new__';
    const catOpts = state.catalog.categories
      .map(c => `<option value="${c}"${c === d.category ? ' selected' : ''}>${c}</option>`).join('');
    const errBanner = state.error
      ? `<div class="error-banner">${escapeHtml(state.error)}</div>` : '';
    const weightVal = state.weightUnknown ? '' : (d.weight_g || 0);
    const weightDisabled = state.weightUnknown ? 'disabled' : '';
    const weightToggleLabel = state.weightUnknown ? '&#x21A9; set weight' : '&#x2717; unk';
    el.innerHTML = `
      ${errBanner}
      <label>Name <input type="text" id="gd-name" value="${escapeHtml(d.name)}"></label>
      <label>Category <select id="gd-category">${catOpts}</select></label>
      <label>Weight (g)
        <div class="weight-row">
          <input type="number" id="gd-weight" min="0" step="1" value="${weightVal}" ${weightDisabled}>
          <button type="button" id="gd-weight-toggle">${weightToggleLabel}</button>
        </div>
      </label>
      <div class="actions">
        <button class="btn" id="gd-save">${isNew ? 'Create' : 'Save'}</button>
        ${isNew ? '' : '<button class="btn danger" id="gd-delete">&times; Delete</button>'}
      </div>
    `;
    document.getElementById('gd-name').addEventListener('input', bindDraftField('name'));
    document.getElementById('gd-category').addEventListener('change', bindDraftField('category'));
    document.getElementById('gd-weight').addEventListener('input', bindDraftField('weight_g', 'int'));
    document.getElementById('gd-weight-toggle').addEventListener('click', () => {
      state.weightUnknown = !state.weightUnknown;
      state.dirty = true;
      renderDetail();
    });
    document.getElementById('gd-save').addEventListener('click', save);
    if (!isNew) document.getElementById('gd-delete').addEventListener('click', () => del(d.id));
  }

  async function save() {
    state.error = '';
    const d = state.draft;
    const isNew = state.selectedId === '__new__';
    const payload = {
      name: d.name,
      category: d.category,
      weight_g: state.weightUnknown ? null : (d.weight_g || 0),
    };
    try {
      let res;
      if (isNew) {
        res = await fetch('/api/gear', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch(`/api/gear/${encodeURIComponent(d.id)}`, {
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
    let res = await fetch(`/api/gear/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (res.status === 409) {
      const j = await res.json();
      const refs = (j.detail && j.detail.references) || [];
      const msg = `This item is used by ${refs.length} trip(s):\n  ${refs.join('\n  ')}\n\nDelete anyway?`;
      if (!confirm(msg)) return;
      res = await fetch(`/api/gear/${encodeURIComponent(id)}?force=true`, { method: 'DELETE' });
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

  function openManageCatsModal() {
    const overlay = document.createElement('div');
    overlay.className = 'gear-cat-modal-overlay';
    overlay.innerHTML = `
      <div class="gear-cat-modal">
        <h3>Manage categories</h3>
        <div class="gear-cat-error" hidden></div>
        <ul class="gear-cat-list"></ul>
        <div class="gear-cat-add">
          <input type="text" id="gca-new" maxlength="40" placeholder="Add category…">
          <button class="btn" id="gca-add-btn">Add</button>
          <button class="btn secondary" id="gca-close">Close</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    overlay.querySelector('#gca-close').addEventListener('click', () => overlay.remove());
    overlay.querySelector('#gca-add-btn').addEventListener('click', () => addCategory(overlay));
    renderCategoryList(overlay);
  }

  function showCatError(overlay, msg) {
    const el = overlay.querySelector('.gear-cat-error');
    el.textContent = msg;
    el.hidden = !msg;
    if (msg) el.style.cssText = 'background:#fee2e2;color:#991b1b;padding:0.5rem;border-radius:4px;margin-bottom:0.6rem';
  }

  function renderCategoryList(overlay) {
    const ul = overlay.querySelector('.gear-cat-list');
    ul.innerHTML = state.catalog.categories.map(c => {
      if (c === 'Other') {
        return `<li class="protected"><span>${escapeHtml(c)}  (default — can't remove)</span></li>`;
      }
      return `<li data-cat="${escapeHtml(c)}">
        <span class="gear-cat-name">${escapeHtml(c)}</span>
        <span>
          <button data-act="rename">Rename</button>
          <button class="danger" data-act="delete">× Delete</button>
        </span>
      </li>`;
    }).join('');
    ul.querySelectorAll('li[data-cat]').forEach(li => {
      const cat = li.dataset.cat;
      li.querySelector('[data-act="rename"]').addEventListener('click',
        () => beginRename(overlay, li, cat));
      li.querySelector('[data-act="delete"]').addEventListener('click',
        () => deleteCategory(overlay, cat));
    });
  }

  function beginRename(overlay, li, cat) {
    const span = li.querySelector('.gear-cat-name');
    const actions = li.querySelector('span:last-child');
    span.outerHTML = `<input class="gear-cat-rename" type="text" value="${escapeHtml(cat)}" maxlength="40" style="flex:1;padding:0.2rem">`;
    actions.innerHTML = `
      <button data-act="save">Save</button>
      <button class="secondary" data-act="cancel">Cancel</button>
    `;
    li.querySelector('[data-act="save"]').addEventListener('click', async () => {
      const newName = li.querySelector('.gear-cat-rename').value.trim();
      if (!newName || newName === cat) { renderCategoryList(overlay); return; }
      const r = await fetch(`/api/gear/categories/${encodeURIComponent(cat)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_name: newName }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        showCatError(overlay, (j.detail && j.detail.error) || `HTTP ${r.status}`);
        return;
      }
      showCatError(overlay, '');
      state.catalog = await fetchCatalog();
      renderCategoryFilter();
      renderList();
      renderCategoryList(overlay);
    });
    li.querySelector('[data-act="cancel"]').addEventListener('click', () => renderCategoryList(overlay));
  }

  async function deleteCategory(overlay, cat) {
    let r = await fetch(`/api/gear/categories/${encodeURIComponent(cat)}`, { method: 'DELETE' });
    if (r.status === 409) {
      const j = await r.json();
      const msg = (j.detail && j.detail.error) || 'in use';
      if (!confirm(`${msg}\n\nReassign affected items to "Other" and delete?`)) return;
      r = await fetch(`/api/gear/categories/${encodeURIComponent(cat)}?force=true`,
                       { method: 'DELETE' });
    }
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      showCatError(overlay, (j.detail && j.detail.error) || `HTTP ${r.status}`);
      return;
    }
    showCatError(overlay, '');
    state.catalog = await fetchCatalog();
    renderCategoryFilter();
    renderList();
    renderCategoryList(overlay);
  }

  async function addCategory(overlay) {
    const inp = overlay.querySelector('#gca-new');
    const name = inp.value.trim();
    if (!name) return;
    const r = await fetch('/api/gear/categories', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      showCatError(overlay, (j.detail && j.detail.error) || `HTTP ${r.status}`);
      return;
    }
    showCatError(overlay, '');
    inp.value = '';
    state.catalog = await fetchCatalog();
    renderCategoryFilter();
    renderList();
    renderCategoryList(overlay);
  }

  async function mount(root) {
    const tpl = document.getElementById('tpl-gear');
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));
    state = { catalog: { categories: [], items: [] }, selectedId: null,
              query: '', category: '', draft: null, weightUnknown: false,
              dirty: false, error: '' };
    state.catalog = await fetchCatalog();
    renderCategoryFilter();
    renderList();
    renderDetail();
    document.getElementById('gear-search').addEventListener('input', (e) => {
      state.query = e.target.value;
      renderList();
    });
    document.getElementById('gear-category-filter').addEventListener('change', (e) => {
      state.category = e.target.value;
      renderList();
    });
    document.getElementById('gear-add').addEventListener('click', () => {
      if (state.dirty && !confirm('Discard unsaved changes?')) return;
      select('__new__');
    });
    document.getElementById('gear-manage-cats').addEventListener('click', openManageCatsModal);
  }

  global.GearPage = { mount };
}(window));
