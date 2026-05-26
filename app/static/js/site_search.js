(function () {
  const grid = document.getElementById('grid');
  if (!grid) return;
  const cards = Array.from(document.querySelectorAll('.site'));
  const lenMinDefault = parseFloat(grid.dataset.lenMin) || 0;
  const lenMaxDefault = parseFloat(grid.dataset.lenMax);

  function getChecked(cls) {
    return new Set(
      Array.from(document.querySelectorAll('.' + cls + ':checked')).map(e => e.value)
    );
  }

  function apply() {
    const camp = getChecked('f-camp');
    const priv = getChecked('f-priv');
    const eq = getChecked('f-eq');
    const lminRaw = parseFloat(document.getElementById('len-min').value);
    const lmaxRaw = parseFloat(document.getElementById('len-max').value);
    const lmin = isNaN(lminRaw) ? -Infinity : lminRaw;
    const lmax = isNaN(lmaxRaw) ? Infinity : lmaxRaw;
    const wp = document.getElementById('with-photos').checked;
    const q = document.getElementById('q').value.toLowerCase();
    let visible = 0;
    cards.forEach(c => {
      const okC = camp.size === 0 || camp.has(c.dataset.camp);
      const okP = priv.size === 0 || priv.has(c.dataset.priv);
      const okE = eq.size === 0 || eq.has(c.dataset.eq);
      const len = parseFloat(c.dataset.len);
      const okL = isNaN(len) ? true : (len >= lmin && len <= lmax);
      const okPh = !wp || parseInt(c.dataset.photos, 10) > 0;
      const okQ = !q || (c.dataset.q || '').includes(q);
      const show = okC && okP && okE && okL && okPh && okQ;
      c.classList.toggle('hidden', !show);
      if (show) visible++;
    });
    const summary = visible + ' / ' + cards.length;
    document.getElementById('count').textContent = summary + ' visible';
    const counter = document.getElementById('counter');
    if (counter) counter.textContent = summary + ' sites match';
  }

  document.querySelectorAll('.filters input').forEach(el => {
    el.addEventListener('change', apply);
    if (el.type === 'search' || el.type === 'number') {
      el.addEventListener('input', apply);
    }
  });

  document.getElementById('reset-filters').onclick = () => {
    document.querySelectorAll('.filters input[type="checkbox"]').forEach(e => {
      e.checked = e.id !== 'with-photos';
    });
    document.getElementById('len-min').value = lenMinDefault;
    if (!isNaN(lenMaxDefault)) document.getElementById('len-max').value = lenMaxDefault;
    document.getElementById('q').value = '';
    apply();
  };
  document.getElementById('check-none-camp').onclick = () => {
    document.querySelectorAll('.f-camp').forEach(e => { e.checked = false; });
    apply();
  };
  document.getElementById('check-all-camp').onclick = () => {
    document.querySelectorAll('.f-camp').forEach(e => { e.checked = true; });
    apply();
  };

  apply();
})();

window.siteLightbox = function (src) {
  var lbi = document.getElementById('lbi');
  var lb = document.getElementById('lb');
  if (!lb || !lbi) return;
  lbi.src = src;
  lb.classList.add('open');
};
