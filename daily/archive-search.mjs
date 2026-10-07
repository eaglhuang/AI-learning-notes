import {LOCALES, validateRecord, weekdayForDate} from './issue-ui.mjs';
export const normalize = value => String(value ?? '').normalize('NFKC').toLowerCase().trim();
const strings = value => typeof value === 'string' ? [value] : value && typeof value === 'object' ? Object.values(value).flatMap(strings) : [];
export function validateIndex(index) {
  if (index?.schemaVersion !== 1 || index.scope !== 'published-newsletter-content' || !Array.isArray(index.editions) || !Array.isArray(index.records) || index.records.length > 10000) throw new TypeError('Invalid archive index');
  index.editions.forEach(weekdayForDate);
  if (new Set(index.editions).size !== index.editions.length) throw new TypeError('Duplicate editions');
  const keys = new Set();
  for (const row of index.records) {
    validateRecord(row);
    if (!index.editions.includes(row.editionDate) || keys.has(row.key)) throw new TypeError('Invalid archive membership');
    keys.add(row.key);
  }
  return index;
}
export function searchArchive(index, query = '', category = 'all') {
  const terms = normalize(query).split(/\s+/).filter(Boolean);
  return index.records.filter(row => (category === 'all' || row.category === category) && terms.every(term => normalize(strings([row.localized, row.editionTitle, row.source, row.keywords, row.aliases]).join(' ')).includes(term)));
}
export function mountArchiveSearch({root, index, locale = 'zh-TW', controller}) {
  validateIndex(index);
  const doc = root.ownerDocument;
  const el = (tag, text) => { const node = doc.createElement(tag); if (text != null) node.textContent = text; return node; };
  const heading = el('h2'), label = el('label'), input = el('input'), catLabel = el('label'), category = el('select'), reset = el('button'), note = el('p'), count = el('p'), results = el('div');
  input.type = 'search'; input.id = 'history-query'; input.autocomplete = 'off'; label.htmlFor = input.id;
  category.id = 'history-category'; catLabel.htmlFor = category.id; reset.type = 'button';
  count.setAttribute('role', 'status'); count.setAttribute('aria-live', 'polite'); results.className = 'archive-search-results';
  for (const name of ['all', ...new Set(index.records.map(row => row.category))]) { const option = el('option', name); option.value = name; category.append(option); }
  const controls = el('div'); controls.className = 'history-controls'; controls.append(label, input, catLabel, category, reset);
  root.replaceChildren(heading, note, controls, count, results);
  const categories = {all:['全部','All'],news:['新聞','News'],papers:['論文','Papers'],tools:['工具','Tools'],products:['產品','Products'],engineering:['工程實戰','Engineering']};
  let currentLocale = locale;
  function render() {
    const en = currentLocale === 'en';
    heading.textContent = en ? 'Search all newsletter content' : '搜尋所有電子報內容';
    label.textContent = en ? 'Keyword' : '關鍵字'; catLabel.textContent = en ? 'Category' : '分類'; reset.textContent = en ? 'Reset' : '重設';
    input.placeholder = en ? 'Title, summary, source or keyword' : '標題、摘要、來源或關鍵字';
    note.textContent = en ? 'Every published edition, with no date limit. Searches stored bilingual content; external full articles are not fetched.' : '不限日期，搜尋所有已發布期數保存的中英文內容；不會抓取外部原文全文。';
    for (const option of category.options) option.textContent = categories[option.value]?.[en ? 1 : 0] || option.value;
    const rows = searchArchive(index, input.value, category.value);
    count.textContent = en ? `${rows.length} of ${index.records.length} picks · ${index.editions.length} editions` : `找到 ${rows.length} / ${index.records.length} 則 · ${index.editions.length} 期`;
    results.replaceChildren();
    if (!rows.length) results.append(el('p', en ? 'No matches. Try another keyword or reset.' : '找不到符合內容，請換個關鍵字或重設。'));
    for (const row of rows) {
      const copy = row.localized[currentLocale], article = el('article'), h = el('h3'), link = el('a', copy.title+' ↗');
      article.className = 'archive-search-result'; link.href = row.sourceUrl; link.rel = 'noopener noreferrer'; link.target = '_blank'; h.append(link);
      const meta = el('p', `${row.editionDate} · ${row.source}`), actions = el('div'); actions.className = 'story-actions';
      if (controller?.supported) {
        const summary = el('button', en ? 'Read summary' : '閱讀摘要'); summary.type = 'button'; summary.setAttribute('aria-haspopup', 'dialog');
        summary.addEventListener('click', () => controller.open(row, summary)); actions.append(summary);
      } else {
        const details = el('details'); details.append(el('summary', en ? 'Read summary' : '閱讀摘要'), el('p', copy.summary), el('p', copy.takeaway), el('p', copy.caveat)); actions.append(details);
      }
      const translation = el('button', en ? 'AI full translation · Not enabled' : 'AI 全文翻譯・尚未啟用'); translation.type = 'button'; translation.disabled = true;
      translation.title = en ? 'Full-text rights and a translation service must be configured.' : '需要核對全文使用權限並設定翻譯服務。';
      const edition = el('a', en ? 'View edition ↗' : '查看期別 ↗'); edition.href = row.permalink[currentLocale];
      actions.append(translation, edition); article.append(meta, h, actions); results.append(article);
    }
  }
  input.addEventListener('input', render); category.addEventListener('change', render);
  reset.addEventListener('click', () => { input.value = ''; category.value = 'all'; render(); input.focus(); });
  render();
  return {setLocale(next) { if (!LOCALES.includes(next)) throw new TypeError('Unsupported locale'); currentLocale = next; render(); }};
}
