const section = document.querySelector('#atomic-daily');
if (section) {
  let locale = 'zh-TW';
  try { if (localStorage.getItem('atomic-daily-language') === 'en') locale = 'en'; } catch { /* optional preference */ }
  function render() {
    section.lang = locale;
    section.querySelectorAll('[data-zh][data-en]').forEach(el => { el.textContent = el.dataset[locale === 'en' ? 'en' : 'zh']; });
    section.querySelectorAll('[data-daily-link]').forEach(el => { const url = new URL(el.href); url.searchParams.set('lang', locale); el.href = url.href; });
  }
  section.querySelector('#daily-home-language')?.addEventListener('click', () => {
    locale = locale === 'en' ? 'zh-TW' : 'en';
    try { localStorage.setItem('atomic-daily-language', locale); } catch { /* optional preference */ }
    render();
  });
  render();
}
