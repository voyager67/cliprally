(() => {
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.querySelector('.primary-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      const open = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!open));
      toggle.setAttribute('aria-label', open ? 'Open navigation' : 'Close navigation');
      document.body.classList.toggle('menu-open', !open);
    });
    nav.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Open navigation');
      document.body.classList.remove('menu-open');
    }));
  }

  document.querySelectorAll('[data-copy]').forEach(button => {
    button.addEventListener('click', async () => {
      const text = button.getAttribute('data-copy') || '';
      try {
        await navigator.clipboard.writeText(text.replaceAll('&#10;', '\n'));
        const old = button.textContent;
        button.textContent = 'Copied';
        button.classList.add('is-copied');
        window.setTimeout(() => {
          button.textContent = old || 'Copy';
          button.classList.remove('is-copied');
        }, 1400);
      } catch {
        button.textContent = 'Select command';
      }
    });
  });

  const year = document.querySelector('#year');
  if (year) year.textContent = String(new Date().getFullYear());
})();