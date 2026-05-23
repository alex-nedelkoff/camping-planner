(function() {
  const sidenav = document.querySelector('.trip-sidenav');
  if (!sidenav) return;
  const links = Array.from(sidenav.querySelectorAll('a[href^="#"]'));
  const targets = links.map(a => {
    const id = a.getAttribute('href').slice(1);
    return id ? document.getElementById(id) : null;
  });

  function update() {
    // Active = the LAST section whose top is above the (offset) viewport top
    const scrollPos = window.scrollY + 120;
    let activeIdx = 0;
    for (let i = 0; i < targets.length; i++) {
      const t = targets[i];
      if (t && t.offsetTop <= scrollPos) activeIdx = i;
    }
    links.forEach((a, i) => a.classList.toggle('active', i === activeIdx));
  }

  // Smooth-scroll on click (overrides any default jump for older browsers).
  links.forEach((a, i) => {
    a.addEventListener('click', (e) => {
      const target = targets[i];
      if (!target) return;
      e.preventDefault();
      const top = target.getBoundingClientRect().top + window.scrollY - 70;
      window.scrollTo({top, behavior: 'smooth'});
      history.replaceState(null, '', a.getAttribute('href'));
    });
  });

  window.addEventListener('scroll', update, {passive: true});
  window.addEventListener('resize', update, {passive: true});
  update();
})();
