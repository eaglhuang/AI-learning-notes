import {bindTopicEditor} from './topic-config.mjs';
import {createSummaryController, bindIssueUI} from './issue-ui.mjs';
import {mountArchiveSearch} from './archive-search.mjs';
/** Progressive enhancement only: all stories and edition links work without JS. */
export const normalize = value => String(value).normalize('NFKC').toLocaleLowerCase().trim();
export function matches({text, category, date}, query = '', filter = 'all', selectedDate = '') {
  return (filter === 'all' || category === filter) && (!selectedDate || date === selectedDate) &&
    normalize(query).split(/\s+/).every(word => normalize(text).includes(word));
}
export function chooseLocale(query, stored, fallback) {
  return [query, stored, fallback].find(value => ['en', 'zh-TW'].includes(value)) || 'zh-TW';
}
export function safeEndpoint(value) {
  try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password; }
  catch { return false; }
}

if (typeof document !== 'undefined') {
  document.documentElement.classList.add('js');
  let saved;
  try { saved = localStorage.getItem('atomic-daily-language'); } catch { /* storage is optional */ }
  const url = new URL(location.href);
  let locale = chooseLocale(url.searchParams.get('lang'), saved, document.body.dataset.defaultLocale);
  let filter = 'all';
  const cards = [...document.querySelectorAll('[data-card]')];
  const search = document.querySelector('#search');
  const date = document.querySelector('#archive-date');
  const count = document.querySelector('#result-count');
  const status = document.querySelector('#subscription-status');
  let statusKey = '';
  let archiveSearch = null;
  let topicEditor = null;
  const summaryUI = createSummaryController({document, window, locale, onLocale: next => setLocale(next, true)});
  bindIssueUI({document, controller: summaryUI});
  const messages = {
    sending: ['正在要求確認信…', 'Requesting a confirmation email…'],
    accepted: ['若此信箱可訂閱，請至收件匣完成確認；尚未確認前不會收到日報。', 'If this address is eligible, check your inbox to confirm. You are not subscribed until confirmation.'],
    failed: ['目前無法確認請求是否完成，請稍後查看信箱再試，或使用 RSS。', 'We could not confirm the request. Check your inbox before trying again, or use RSS.'],
    consent: ['請填入有效信箱，並勾選接收摘要的同意欄位。', 'Enter a valid email and agree to receive summaries.']
  };
  const showStatus = key => { statusKey = key; if (status) status.textContent = messages[key]?.[locale === 'en' ? 1 : 0] || ''; };
  function renderFilters() {
    let visible = 0;
    cards.forEach(card => {
      let data = {};
      try { data = JSON.parse(card.dataset.search); } catch { /* safe empty search */ }
      card.hidden = !matches({text: Object.values(data).join(' '), category: card.dataset.category, date: card.dataset.date}, search?.value, filter, date?.value);
      if (!card.hidden) visible++;
    });
    if (count) count.textContent = locale === 'en' ? `${visible} of ${cards.length} shown` : `顯示 ${visible} / ${cards.length} 則`;
    const empty = document.querySelector('#empty-state');
    if (empty) empty.hidden = visible !== 0;
  }
  function setLocale(next, persist = false) {
    locale = next;
    document.documentElement.lang = locale;
    document.querySelectorAll('[data-zh][data-en]').forEach(el => { el.textContent = el.dataset[locale === 'en' ? 'en' : 'zh']; });
    document.querySelectorAll('[data-placeholder-zh]').forEach(el => { el.placeholder = el.dataset[locale === 'en' ? 'placeholderEn' : 'placeholderZh']; });
    document.querySelectorAll('[data-alt-zh]').forEach(el => { el.alt = el.dataset[locale === 'en' ? 'altEn' : 'altZh']; });
    document.querySelectorAll('[data-title-zh]').forEach(el => { el.title = el.dataset[locale === 'en' ? 'titleEn' : 'titleZh']; });
    document.querySelectorAll('[data-aria-zh]').forEach(el => { el.setAttribute('aria-label', el.dataset[locale === 'en' ? 'ariaEn' : 'ariaZh']); });
    document.querySelectorAll('[data-local-link]').forEach(el => { const link = new URL(el.href, location.href); link.searchParams.set('lang',locale); el.href = link.href; });
    const toggle = document.querySelector('#language');
    if (toggle) { toggle.setAttribute('aria-label', locale === 'en' ? '切換為繁體中文' : 'Switch to English'); toggle.setAttribute('lang', locale === 'en' ? 'zh-TW' : 'en'); }
    if (persist) {
      try { localStorage.setItem('atomic-daily-language', locale); } catch { /* storage is optional */ }
      const nextUrl = new URL(location.href); nextUrl.searchParams.set('lang', locale); history.replaceState(null, '', nextUrl);
    }
    renderFilters();
    summaryUI.setLocale(locale);
    archiveSearch?.setLocale(locale);
    topicEditor?.setLocale(locale);
    if (statusKey) showStatus(statusKey);
  }
  document.querySelector('#language')?.addEventListener('click', event => { event.preventDefault(); setLocale(locale === 'en' ? 'zh-TW' : 'en', true); });
  document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    filter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    renderFilters();
  }));
  search?.addEventListener('input', renderFilters);
  date?.addEventListener('change', renderFilters);
  document.querySelector('#clear-filters')?.addEventListener('click', () => {
    filter = 'all'; if (search) search.value = ''; if (date) date.value = '';
    document.querySelectorAll('[data-filter]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.filter === 'all')));
    renderFilters(); search?.focus();
  });
  document.querySelector('#issue-date')?.addEventListener('change', event => {
    const target = new URL(event.target.value, location.href);
    if (target.origin !== location.origin) return;
    target.searchParams.set('lang', locale); location.assign(target.href);
  });
  document.querySelector('#print-issue')?.addEventListener('click', () => window.print());
  const form = document.querySelector('#subscription');
  if (form && safeEndpoint(form.dataset.endpoint)) {
    const button = form.querySelector('button[type=submit]'); button.disabled = false;
    let pending = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (pending) return;
      if (!form.checkValidity()) { form.reportValidity(); showStatus('consent'); return; }
      pending = true; button.disabled = true; showStatus('sending');
      try {
        const response = await fetch(form.dataset.endpoint, {method:'POST',credentials:'omit',referrerPolicy:'no-referrer',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:form.elements.email.value.trim(),locale,consent:form.elements.consent.checked,website:form.elements.website.value}),signal:AbortSignal.timeout(15000)});
        const result = await response.json();
        if (response.status !== 202 || result.status !== 'confirmation_requested') throw new Error('unconfirmed');
        form.reset(); showStatus('accepted');
      } catch { showStatus('failed'); }
      finally { pending = false; button.disabled = false; }
    });
  }
  topicEditor = bindTopicEditor(document, locale);
  setLocale(locale);
  const archiveRoot = document.querySelector('#all-history-search');
  if (archiveRoot) {
    const indexUrl = new URL(archiveRoot.dataset.indexUrl, location.href);
    if (indexUrl.origin === location.origin) {
      fetch(indexUrl.href, {credentials: 'omit', signal: AbortSignal.timeout(15000)}).then(async response => {
        if (!response.ok) throw new Error('Archive unavailable');
        const raw = await response.text(); if (raw.length > 4000000) throw new Error('Archive too large');
        archiveSearch = mountArchiveSearch({root: archiveRoot, index: JSON.parse(raw), locale, controller: summaryUI});
      }).catch(() => {
        const p = document.createElement('p'); p.dataset.zh = '跨期搜尋暫時無法載入，請使用下方期別連結。'; p.dataset.en = 'Archive search could not load. Use the edition links below.';
        p.textContent = p.dataset[locale === 'en' ? 'en' : 'zh']; p.setAttribute('role', 'status'); archiveRoot.append(p);
      });
    }
  }
  window.addEventListener('pageshow', renderFilters);
}
