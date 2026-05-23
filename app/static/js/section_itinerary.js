(function() {
  const sectionEl = document.querySelector('[data-section="itinerary"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;

  function renderEdit(itinerary) {
    const wrap = document.createElement('div');
    wrap.innerHTML = `<div class="days"></div>
      <button class="btn btn-ghost add-day">+ day</button>`;
    const daysDiv = wrap.querySelector('.days');
    function addDay(d = {date:'', label:'', notes:''}) {
      const block = document.createElement('div');
      block.className = 'day-edit';
      block.innerHTML = `<div class="day-head">
          <input type="date" class="d-date" value="${d.date||''}">
          <input class="d-label" placeholder="label" value="${d.label||''}">
          <button class="btn btn-ghost rm-day">remove</button>
        </div>
        <textarea class="d-notes" rows="6">${(d.notes||'').replace(/</g,'&lt;')}</textarea>`;
      block.querySelector('.rm-day').onclick = () => block.remove();
      daysDiv.appendChild(block);
    }
    (itinerary || []).forEach(addDay);
    wrap.querySelector('.add-day').onclick = () => addDay();
    return wrap;
  }

  function collectEdit(root) {
    const days = [];
    root.querySelectorAll('.day-edit').forEach(block => {
      days.push({
        date: block.querySelector('.d-date').value,
        label: block.querySelector('.d-label').value,
        notes: block.querySelector('.d-notes').value,
      });
    });
    return days;
  }

  SectionEditor.setup({name: 'itinerary', readEl: sectionEl, slug,
                       renderEdit, collectEdit});
})();
