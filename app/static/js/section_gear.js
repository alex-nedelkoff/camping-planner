(function() {
  const sectionEl = document.querySelector('[data-section="gear"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /**
   * Editable dropdown (combobox): input + chevron + list of suggestions.
   * `getOptions()` is called fresh each time the dropdown opens, so newly-
   * added categories from other rows show up immediately.
   */
  function makeCategoryCombo(value, getOptions) {
    const wrap = document.createElement('div');
    wrap.className = 'cat-combo';
    wrap.innerHTML = `
      <input class="g-cat" value="${esc(value)}" placeholder="category" autocomplete="off">
      <button type="button" class="cat-chevron" tabindex="-1" aria-label="show categories">&#9662;</button>
      <ul class="cat-dropdown" hidden></ul>`;
    const input = wrap.querySelector('input.g-cat');
    const chev = wrap.querySelector('.cat-chevron');
    const list = wrap.querySelector('.cat-dropdown');

    function showList(filter = '') {
      const all = getOptions();
      const lower = filter.toLowerCase();
      const filtered = filter
        ? all.filter(c => c.toLowerCase().includes(lower) && c.toLowerCase() !== lower)
        : all;
      list.innerHTML = '';
      if (filtered.length === 0) { list.hidden = true; return; }
      for (const c of filtered) {
        const li = document.createElement('li');
        li.textContent = c;
        // mousedown fires before input.blur, so the click registers
        li.addEventListener('mousedown', (e) => {
          e.preventDefault();
          input.value = c;
          list.hidden = true;
        });
        list.appendChild(li);
      }
      list.hidden = false;
    }
    function hideList() { list.hidden = true; }

    input.addEventListener('focus', () => showList(input.value));
    input.addEventListener('input', () => showList(input.value));
    input.addEventListener('blur', () => setTimeout(hideList, 120));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { hideList(); input.blur(); }
    });
    chev.addEventListener('mousedown', (e) => {
      e.preventDefault();
      if (list.hidden) { input.focus(); showList(''); }
      else { hideList(); }
    });
    return wrap;
  }

  function renderEdit(gear, trip) {
    const participants = (trip && trip.participants) || [];
    const wrap = document.createElement('div');
    wrap.className = 'gear-edit-wrap';

    const hint = document.createElement('p');
    hint.className = 'edit-hint';
    hint.textContent = 'Check the box under each person bringing/packing the item. Check Shared if it’s community gear (canoe, bear barrel, tarp). Multiple checks = each person brings their own copy.';
    wrap.appendChild(hint);

    const table = document.createElement('table');
    table.className = 'gear-edit-table';
    let header = '<thead><tr><th class="cat-col">Category</th><th>Item</th><th>Notes</th>';
    for (const p of participants) header += `<th>${esc(p)}</th>`;
    header += '<th>Shared</th><th class="rm-col"></th></tr></thead>';
    table.innerHTML = header + '<tbody></tbody>';
    wrap.appendChild(table);
    const tbody = table.querySelector('tbody');

    /** Live-recomputed list of unique categories across all rows. */
    function currentCategories() {
      const set = new Set();
      tbody.querySelectorAll('input.g-cat').forEach(el => {
        const v = el.value.trim();
        if (v) set.add(v);
      });
      return Array.from(set).sort((a, b) => a.localeCompare(b));
    }

    function addRow(it = {item:'', category:'', notes:'', bringers:[], shared:false}) {
      const tr = document.createElement('tr');
      // Build cells without the category yet — that goes in via combobox
      let cells = `<td class="cat-cell"></td>`;
      cells += `<td><input class="g-item" value="${esc(it.item)}" placeholder="item"></td>`;
      cells += `<td><input class="g-notes" value="${esc(it.notes)}"></td>`;
      for (const p of participants) {
        const checked = (it.bringers || []).includes(p) ? "checked" : "";
        cells += `<td class="cb-cell"><input type="checkbox" class="g-who" data-who="${esc(p)}" ${checked}></td>`;
      }
      cells += `<td class="cb-cell"><input type="checkbox" class="g-shared" ${it.shared ? 'checked' : ''}></td>`;
      cells += `<td class="rm-cell"><button type="button" class="btn-icon rm-row" title="remove">×</button></td>`;
      tr.innerHTML = cells;
      // Insert the combobox into the category cell
      tr.querySelector('.cat-cell').appendChild(
        makeCategoryCombo(it.category, currentCategories)
      );
      tr.querySelector('.rm-row').onclick = () => tr.remove();
      tbody.appendChild(tr);
    }

    const sorted = (gear || []).slice().sort((a, b) =>
      (a.category || '').localeCompare(b.category || '') ||
      (a.item || '').localeCompare(b.item || '')
    );
    sorted.forEach(addRow);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-ghost add-row';
    addBtn.textContent = '+ item';
    addBtn.onclick = () => addRow();
    wrap.appendChild(addBtn);

    if (participants.length === 0) {
      const warn = document.createElement('p');
      warn.className = 'edit-hint warn';
      warn.textContent = 'No participants on this trip — add some via "Edit trip details" first, then per-attendee columns will appear.';
      wrap.insertBefore(warn, hint);
    }
    return wrap;
  }

  function collectEdit(root) {
    const out = [];
    root.querySelectorAll('tbody tr').forEach(tr => {
      const item = tr.querySelector('.g-item').value.trim();
      if (!item) return;
      const bringers = [];
      tr.querySelectorAll('input.g-who:checked').forEach(cb => {
        bringers.push(cb.dataset.who);
      });
      out.push({
        item,
        category: tr.querySelector('.g-cat').value.trim(),
        notes: tr.querySelector('.g-notes').value,
        bringers,
        shared: tr.querySelector('.g-shared').checked,
      });
    });
    return out;
  }

  SectionEditor.setup({name: 'gear', readEl: sectionEl, slug, renderEdit, collectEdit});
})();
