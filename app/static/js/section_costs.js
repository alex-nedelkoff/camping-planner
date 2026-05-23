(function() {
  const sectionEl = document.querySelector('[data-section="costs"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function renderEdit(costs) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `
      <table class="costs-edit"><thead>
        <tr><th>Item</th><th>Who paid</th><th>Amount</th><th>Currency</th><th></th></tr>
      </thead><tbody></tbody></table>
      <button class="btn btn-ghost add-row">+ row</button>`;
    const tbody = wrap.querySelector('tbody');
    function addRow(r = {item:'', who_paid:'', amount:'', currency:'CAD'}) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td><input class="c-item" value="${r.item||''}"></td>
        <td><input class="c-who" value="${r.who_paid||''}"></td>
        <td><input class="c-amt" type="number" step="0.01" value="${r.amount ?? ''}"></td>
        <td><input class="c-cur" value="${r.currency||'CAD'}" size="4"></td>
        <td><button class="btn btn-ghost rm">×</button></td>`;
      tr.querySelector('.rm').onclick = () => tr.remove();
      tbody.appendChild(tr);
    }
    (costs || []).forEach(addRow);
    wrap.querySelector('.add-row').onclick = () => addRow();
    return wrap;
  }

  function collectEdit(root) {
    const rows = [];
    root.querySelectorAll('.costs-edit tbody tr').forEach(tr => {
      const amt = tr.querySelector('.c-amt').value;
      rows.push({
        item: tr.querySelector('.c-item').value,
        who_paid: tr.querySelector('.c-who').value,
        amount: amt === '' ? null : Number(amt),
        currency: tr.querySelector('.c-cur').value || 'CAD',
      });
    });
    return rows;
  }

  SectionEditor.setup({
    name: 'costs', readEl: sectionEl, slug,
    renderEdit, collectEdit,
  });
})();
