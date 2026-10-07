/** Shared summary dialog and date-based layout. Editorial strings are text, never markup. */
export const LOCALES = ['zh-TW', 'en'];
export function safeHttps(value) {
  if (typeof value !== 'string' || /[\u0000-\u0020\u007f\\]/.test(value)) return '';
  try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : ''; }
  catch { return ''; }
}
export function safeSummarySource(value) {
  if (typeof value !== 'string' || [...value].length > 2000 || !value.isWellFormed()
      || /\s|[\u0085]/.test(value)) return '';
  const match = /^https:\/\/([a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::443)?(?=[/?#]|$)/i.exec(value);
  if (!match) return '';
  const host = match[1], labels = host.split('.');
  if (host.length > 253 || !/^[a-z]/i.test(labels.at(-1))
      || labels.some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label))) return '';
  const url = safeHttps(value);
  return url;
}
export function weekdayForDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) throw new TypeError('Expected an edition calendar date');
  const d = new Date(`${value}T12:00:00Z`);
  if (!Number.isFinite(d.getTime()) || d.toISOString().slice(0, 10) !== value) throw new TypeError('Invalid edition date');
  return (d.getUTCDay() + 6) % 7;
}
export function validateRecord(row) {
  if (!row || typeof row !== 'object' || !/^[a-z0-9][a-z0-9-]*$/.test(row.storyId || '')) throw new TypeError('Invalid story ID');
  weekdayForDate(row.editionDate); weekdayForDate(row.sourcePublishedDate);
  if (row.key !== `${row.editionDate}:${row.storyId}` || !safeHttps(row.sourceUrl)) throw new TypeError('Invalid story binding');
  for (const field of ['source', 'category']) if (typeof row[field] !== 'string' || !row[field]) throw new TypeError('Missing story metadata');
  for (const lang of LOCALES) {
    for (const field of ['title', 'summary', 'takeaway', 'caveat']) if (typeof row.localized?.[lang]?.[field] !== 'string' || !row.localized[lang][field].trim()) throw new TypeError('Missing bilingual content');
    if (!safeHttps(row.permalink?.[lang])) throw new TypeError('Invalid permalink');
  }
  if (row.summarySources !== undefined && (!Array.isArray(row.summarySources) || row.summarySources.length > 8 || row.summarySources.some(url => !safeSummarySource(url)) || new Set(row.summarySources).size !== row.summarySources.length)) throw new TypeError('Invalid summary sources');
  if (row.shortSummaryReason != null && !['source_budget','verified_source_scope'].includes(row.shortSummaryReason)) throw new TypeError('Invalid short-summary reason');
  if (row.sourceOnly !== undefined && typeof row.sourceOnly !== 'boolean') throw new TypeError('Invalid summary mode');
  return row;
}

export function shortSummaryNote(row, locale) {
  if (!row.shortSummaryReason) return '';
  return locale === 'en' ? 'Shorter summary: limited to verified source material and permitted condensation.' : '本則採較短摘要：以已核對的原文內容與摘要使用範圍為限。';
}

export function appendSummarySources(doc, root, sources = []) {
  root.replaceChildren();
  for (const [index, url] of sources.entries()) {
    const safe = safeSummarySource(url);
    if (!safe) throw new TypeError('Invalid summary source URL');
    const li = doc.createElement('li'), link = doc.createElement('a');
    link.href = safe; link.target = '_blank'; link.rel = 'noopener noreferrer';
    link.textContent = `${index + 1} · ${new URL(safe).hostname}`; li.append(link); root.append(li);
  }
}

export function createSummaryController({document: doc, window: win, locale = 'zh-TW', onLocale}) {
  const dialog = doc.querySelector('#summary-dialog');
  const supported = Boolean(dialog && typeof dialog.showModal === 'function' && typeof dialog.close === 'function');
  let currentLocale = locale, current = null, opener = null, scroll = null, overflow = '';
  if (!supported) return {supported, open: () => false, close() {}, setLocale() {}, activeKey: () => null};
  doc.documentElement.classList.add('has-summary-dialog');
  const put = (selector, text) => { dialog.querySelector(selector).textContent = text; };
  const render = () => {
    if (!current) return;
    const text = current.localized[currentLocale], en = currentLocale === 'en';
    put('#summary-title', text.title); put('[data-dialog-summary]', text.summary);
    put('[data-dialog-takeaway]', text.takeaway); put('[data-dialog-caveat]', text.caveat);
    put('[data-dialog-highlight-label]', current.sourceOnly ? (en ? 'Source highlight' : '原文重點') : (en ? 'Takeaway' : '實作啟示'));
    const note = dialog.querySelector('[data-dialog-length-note]');
    note.textContent = shortSummaryNote(current, currentLocale); note.hidden = !note.textContent;
    const sources = dialog.querySelector('[data-dialog-sources]');
    appendSummarySources(doc, sources, current.summarySources || []);
    const label = dialog.querySelector('[data-dialog-sources-label]');
    label.textContent = en ? 'Summary sources' : '摘要來源'; label.hidden = !current.summarySources?.length;
    put('[data-dialog-meta]', `${en ? 'Edition' : '期別'} ${current.editionDate} · ${current.source} · ${current.sourcePublishedDate}`);
    dialog.querySelector('[data-dialog-source]').href = safeHttps(current.sourceUrl);
    dialog.setAttribute('lang', currentLocale);
    dialog.dataset.activeKey = current.key;
  };
  const restore = () => {
    if (scroll === null) return;
    doc.body.style.overflow = overflow;
    const target = opener?.isConnected && !opener.hidden ? opener : doc.querySelector('#all-history-search input') || doc.querySelector('#language');
    target?.focus({preventScroll: true});
    win.scrollTo({left: scroll.x, top: scroll.y, behavior: 'instant'});
    scroll = null; current = null; opener = null; delete dialog.dataset.activeKey;
  };
  const close = () => { if (dialog.open) dialog.close(); restore(); };
  dialog.querySelector('[data-dialog-close]').addEventListener('click', close);
  dialog.querySelector('[data-dialog-language]').addEventListener('click', () => onLocale?.(currentLocale === 'en' ? 'zh-TW' : 'en'));
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  dialog.addEventListener('close', restore);
  dialog.addEventListener('click', event => {
    const box = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) close();
  });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const nodes = [...dialog.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),[tabindex="0"]')].filter(el => !el.hidden);
    const first = nodes[0], last = nodes.at(-1);
    if (!first) { event.preventDefault(); return; }
    if (event.shiftKey && doc.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && doc.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  return {
    supported,
    open(row, from) {
      validateRecord(row);
      if (!dialog.open) {
        opener = from || doc.activeElement; scroll = {x: win.scrollX, y: win.scrollY}; overflow = doc.body.style.overflow;
      }
      current = row; render();
      if (!dialog.open) dialog.showModal();
      doc.body.style.overflow = 'hidden'; dialog.scrollTop = 0;
      dialog.querySelector('[data-dialog-close]').focus({preventScroll: true});
      return true;
    },
    close,
    setLocale(next) { if (!LOCALES.includes(next)) throw new TypeError('Unsupported locale'); currentLocale = next; render(); },
    activeKey: () => current?.key || null
  };
}

export function bindIssueUI({document: doc, controller}) {
  const wrapper = doc.querySelector('.enhanced-issue');
  if (!wrapper) return;
  const data = JSON.parse(doc.querySelector('#issue-content').textContent);
  const rows = new Map(data.records.map(row => [validateRecord(row).key, row]));
  if (rows.size !== data.records.length) throw new TypeError('Duplicate story keys');
  const picker = doc.querySelector('#weekday-layout');
  const dialogPicker = doc.querySelector('#dialog-layout');
  wrapper.dataset.weekday = String(weekdayForDate(wrapper.dataset.editionDate));
  for (const select of [picker, dialogPicker].filter(Boolean)) {
    select.value = wrapper.dataset.weekday;
    select.addEventListener('change', () => {
      if (/^[0-6]$/.test(select.value)) {
        wrapper.dataset.weekday = select.value;
        for (const other of [picker, dialogPicker].filter(Boolean)) other.value = select.value;
      }
    });
  }
  doc.querySelectorAll('[data-summary-key]').forEach(button => {
    button.addEventListener('click', () => { const row = rows.get(button.dataset.summaryKey); if (row) controller.open(row, button); });
  });
  doc.querySelectorAll('.story-image img').forEach(img => {
    const fail = () => {
      img.hidden = true;
      const fallback = img.parentElement.querySelector('.image-fallback'); fallback.hidden = false;
      fallback.setAttribute('role', 'img'); fallback.setAttribute('aria-label', img.alt);
      fallback.dataset.ariaZh = img.dataset.altZh; fallback.dataset.ariaEn = img.dataset.altEn;
    };
    img.addEventListener('error', fail);
    if (img.complete && !img.naturalWidth) fail();
  });
}
