(function() {
  const sectionEl = document.querySelector('[data-section="gear"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function renderEdit(gear) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `
      <h3>Shared</h3>
      <table class="gear-shared-edit"><thead>
        <tr><th>Item</th><th>Who</th><th>Notes</th><th></th></tr>
      </thead><tbody></tbody></table>
      <button class="btn btn-ghost add-shared">+ row</button>
      <h3>Personal</h3>
      <div class="personal-edit"></div>
      <button class="btn btn-ghost add-person">+ person</button>`;
    const sharedTbody = wrap.querySelector('.gear-shared-edit tbody');
    function addSharedRow(row = {item:'', who:'', notes:''}) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td><input value="${row.item || ''}"></td>
        <td><input value="${row.who || ''}"></td>
        <td><input value="${row.notes || ''}"></td>
        <td><button class="btn btn-ghost delete">×</button></td>`;
      tr.querySelector('.delete').onclick = () => tr.remove();
      sharedTbody.appendChild(tr);
    }
    (gear.shared || []).forEach(addSharedRow);
    wrap.querySelector('.add-shared').onclick = () => addSharedRow();

    const personalDiv = wrap.querySelector('.personal-edit');
    function addPerson(p = {person:'', items:[]}) {
      const block = document.createElement('div');
      block.className = 'person-edit';
      block.innerHTML = `<input class="person-name" value="${p.person || ''}" placeholder="name">
        <ul class="items"></ul>
        <button class="btn btn-ghost add-item">+ item</button>
        <button class="btn btn-ghost rm-person">remove person</button>`;
      const ul = block.querySelector('.items');
      function addItem(i = {item:'', notes:''}) {
        const li = document.createElement('li');
        li.innerHTML = `<input class="i-item" value="${i.item || ''}">
          <input class="i-notes" value="${i.notes || ''}" placeholder="notes">
          <button class="btn btn-ghost rm-item">×</button>`;
        li.querySelector('.rm-item').onclick = () => li.remove();
        ul.appendChild(li);
      }
      (p.items || []).forEach(addItem);
      block.querySelector('.add-item').onclick = () => addItem();
      block.querySelector('.rm-person').onclick = () => block.remove();
      personalDiv.appendChild(block);
    }
    (gear.personal || []).forEach(addPerson);
    wrap.querySelector('.add-person').onclick = () => addPerson();
    return wrap;
  }

  function collectEdit(root) {
    const shared = [];
    root.querySelectorAll('.gear-shared-edit tbody tr').forEach(tr => {
      const inputs = tr.querySelectorAll('input');
      shared.push({item: inputs[0].value, who: inputs[1].value, notes: inputs[2].value});
    });
    const personal = [];
    root.querySelectorAll('.person-edit').forEach(block => {
      const items = [];
      block.querySelectorAll('.items li').forEach(li => {
        items.push({
          item: li.querySelector('.i-item').value,
          notes: li.querySelector('.i-notes').value,
        });
      });
      personal.push({
        person: block.querySelector('.person-name').value,
        items,
      });
    });
    return {shared, personal};
  }

  SectionEditor.setup({
    name: 'gear', readEl: sectionEl, slug,
    renderEdit, collectEdit,
  });
})();
