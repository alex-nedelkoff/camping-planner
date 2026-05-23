(function() {
  const sectionEl = document.querySelector('[data-section="gear"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
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
    let header = '<thead><tr><th>Category</th><th>Item</th><th>Notes</th>';
    for (const p of participants) header += `<th>${esc(p)}</th>`;
    header += '<th>Shared</th><th class="rm-col"></th></tr></thead>';
    table.innerHTML = header + '<tbody></tbody>';
    wrap.appendChild(table);
    const tbody = table.querySelector('tbody');

    // Collect unique existing categories for a datalist suggestion
    const cats = Array.from(new Set((gear || []).map(it => it.category).filter(Boolean))).sort();
    const datalist = document.createElement('datalist');
    datalist.id = 'gear-cats';
    cats.forEach(c => {
      const o = document.createElement('option'); o.value = c; datalist.appendChild(o);
    });
    wrap.appendChild(datalist);

    function addRow(it = {item:'', category:'', notes:'', bringers:[], shared:false}) {
      const tr = document.createElement('tr');
      let cells = `<td><input class="g-cat" list="gear-cats" value="${esc(it.category)}" placeholder="category"></td>`;
      cells += `<td><input class="g-item" value="${esc(it.item)}" placeholder="item"></td>`;
      cells += `<td><input class="g-notes" value="${esc(it.notes)}"></td>`;
      for (const p of participants) {
        const checked = (it.bringers || []).includes(p) ? "checked" : "";
        cells += `<td class="cb-cell"><input type="checkbox" class="g-who" data-who="${esc(p)}" ${checked}></td>`;
      }
      cells += `<td class="cb-cell"><input type="checkbox" class="g-shared" ${it.shared ? 'checked' : ''}></td>`;
      cells += `<td class="rm-cell"><button type="button" class="btn-icon rm-row" title="remove">×</button></td>`;
      tr.innerHTML = cells;
      tr.querySelector('.rm-row').onclick = () => tr.remove();
      tbody.appendChild(tr);
    }
    // Sort by category in the editor too
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
      if (!item) return;  // drop empty rows
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
