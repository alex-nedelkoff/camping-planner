(function() {
  const sectionEl = document.querySelector('[data-section="packing"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function renderEdit(packing) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `<div class="categories"></div>
      <button class="btn btn-ghost add-cat">+ category</button>`;
    const catsDiv = wrap.querySelector('.categories');
    function addCat(c = {category:'', items:[]}) {
      const block = document.createElement('div');
      block.className = 'cat-edit';
      block.innerHTML = `<input class="cat-name" value="${c.category||''}">
        <ul class="items"></ul>
        <button class="btn btn-ghost add-item">+ item</button>
        <button class="btn btn-ghost rm-cat">remove category</button>`;
      const ul = block.querySelector('.items');
      function addItem(i = {label:'', checked:false}) {
        const li = document.createElement('li');
        li.innerHTML = `<input type="checkbox" ${i.checked?'checked':''}>
          <input class="lbl" value="${i.label||''}">
          <button class="btn btn-ghost rm">×</button>`;
        li.querySelector('.rm').onclick = () => li.remove();
        ul.appendChild(li);
      }
      (c.items || []).forEach(addItem);
      block.querySelector('.add-item').onclick = () => addItem();
      block.querySelector('.rm-cat').onclick = () => block.remove();
      catsDiv.appendChild(block);
    }
    (packing || []).forEach(addCat);
    wrap.querySelector('.add-cat').onclick = () => addCat();
    return wrap;
  }

  function collectEdit(root) {
    const cats = [];
    root.querySelectorAll('.cat-edit').forEach(block => {
      const items = [];
      block.querySelectorAll('.items li').forEach(li => {
        items.push({
          label: li.querySelector('.lbl').value,
          checked: li.querySelector('input[type=checkbox]').checked,
        });
      });
      cats.push({category: block.querySelector('.cat-name').value, items});
    });
    return cats;
  }

  SectionEditor.setup({name: 'packing', readEl: sectionEl, slug,
                       renderEdit, collectEdit});
})();
