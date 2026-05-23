(function() {
  const sectionEl = document.querySelector('[data-section="food"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function slugify(s) {
    return s.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'') || 'slot';
  }

  function renderEdit(food) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `<div class="slots"></div>
      <button class="btn btn-ghost add-slot">+ meal slot</button>`;
    const slotsDiv = wrap.querySelector('.slots');
    function addSlot(s = {slot:'', label:'', items:[], notes:''}) {
      const block = document.createElement('div');
      block.className = 'slot-edit';
      block.innerHTML = `<div class="slot-head">
          <input class="s-label" value="${s.label||''}" placeholder="meal label">
          <button class="btn btn-ghost rm-slot">remove</button></div>
        <ul class="s-items"></ul>
        <button class="btn btn-ghost add-item">+ item</button>
        <textarea class="s-notes" rows="3" placeholder="notes (markdown)">${(s.notes||'').replace(/</g,'&lt;')}</textarea>`;
      const ul = block.querySelector('.s-items');
      function addItem(i = {name:'', who:''}) {
        const li = document.createElement('li');
        li.innerHTML = `<input class="i-name" value="${i.name||''}">
          <input class="i-who" value="${i.who||''}" placeholder="who">
          <button class="btn btn-ghost rm">×</button>`;
        li.querySelector('.rm').onclick = () => li.remove();
        ul.appendChild(li);
      }
      (s.items||[]).forEach(addItem);
      block.querySelector('.add-item').onclick = () => addItem();
      block.querySelector('.rm-slot').onclick = () => block.remove();
      block.dataset.slot = s.slot || '';
      slotsDiv.appendChild(block);
    }
    (food||[]).forEach(addSlot);
    wrap.querySelector('.add-slot').onclick = () => addSlot();
    return wrap;
  }

  function collectEdit(root) {
    const out = [];
    root.querySelectorAll('.slot-edit').forEach(block => {
      const label = block.querySelector('.s-label').value;
      const slotKey = block.dataset.slot || slugify(label);
      const items = [];
      block.querySelectorAll('.s-items li').forEach(li => {
        items.push({
          name: li.querySelector('.i-name').value,
          who: li.querySelector('.i-who').value,
        });
      });
      out.push({slot: slotKey, label, items,
                notes: block.querySelector('.s-notes').value});
    });
    return out;
  }

  SectionEditor.setup({name:'food', readEl:sectionEl, slug,
                       renderEdit, collectEdit});
})();
