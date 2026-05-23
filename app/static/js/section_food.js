(function() {
  const sectionEl = document.querySelector('[data-section="food"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function slugify(s) {
    return s.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'') || 'slot';
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function renderEdit(food, trip) {
    const participants = (trip && trip.participants) || [];
    const wrap = document.createElement('div');
    wrap.className = 'food-edit-wrap';
    const table = document.createElement('table');
    table.className = 'food-edit-table';
    let header = '<thead><tr><th class="meal-col">Meal</th>';
    for (const p of participants) header += `<th>${esc(p)}</th>`;
    header += '<th class="notes-col">Notes (markdown)</th><th class="rm-col"></th></tr></thead>';
    table.innerHTML = header + '<tbody></tbody>';
    wrap.appendChild(table);
    const tbody = table.querySelector('tbody');

    function addRow(s = {slot:'', label:'', items:[], notes:''}) {
      const tr = document.createElement('tr');
      tr.dataset.slot = s.slot || '';
      let cells = `<td><input class="f-label" value="${esc(s.label)}" placeholder="meal label"></td>`;
      for (const p of participants) {
        const lines = (s.items || []).filter(it => it.who === p).map(it => it.name).join('\n');
        cells += `<td><textarea class="f-cell" data-who="${esc(p)}" rows="3" placeholder="one item per line">${esc(lines)}</textarea></td>`;
      }
      cells += `<td><textarea class="f-notes" rows="3" placeholder="optional">${esc(s.notes)}</textarea></td>`;
      cells += `<td class="rm-cell"><button type="button" class="btn-icon rm-slot" title="remove meal">×</button></td>`;
      tr.innerHTML = cells;
      tr.querySelector('.rm-slot').onclick = () => tr.remove();
      tbody.appendChild(tr);
    }
    (food || []).forEach(addRow);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-ghost add-meal';
    addBtn.textContent = '+ meal';
    addBtn.onclick = () => addRow();
    wrap.appendChild(addBtn);

    if (participants.length === 0) {
      const warn = document.createElement('p');
      warn.className = 'edit-hint warn';
      warn.textContent = 'No participants on this trip — add some via "Edit trip details" first, then the per-attendee columns will appear.';
      wrap.insertBefore(warn, table);
    }
    return wrap;
  }

  function collectEdit(root) {
    const out = [];
    root.querySelectorAll('tbody tr').forEach(tr => {
      const label = tr.querySelector('.f-label').value.trim();
      const slotKey = tr.dataset.slot || slugify(label);
      const items = [];
      tr.querySelectorAll('.f-cell').forEach(cell => {
        const who = cell.dataset.who;
        cell.value.split('\n').forEach(line => {
          const name = line.trim();
          if (name) items.push({name, who});
        });
      });
      out.push({
        slot: slotKey,
        label,
        items,
        notes: tr.querySelector('.f-notes').value,
      });
    });
    return out;
  }

  SectionEditor.setup({name: 'food', readEl: sectionEl, slug, renderEdit, collectEdit});
})();
