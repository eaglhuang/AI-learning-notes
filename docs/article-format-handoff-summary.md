# 文章格式統一交接摘要

這份摘要是給後續接手的人看的，重點只有一件事：
**AI Learning Notes 的文章頁，已經收斂到共用底座 `assets/css/article-base.css` + `assets/js/article-base.js`。**

## 目前狀態

- 首頁仍維持自己的首頁版型與資訊結構。
- 所有文章頁改走同一套文章底座。
- 中英文文章頁共用同一套 token、版型、footer、`Top` 錨點、traffic counter、overlay 與 figure 下載互動。
- 各篇文章不再自己長出一套獨立的頁尾或整頁 shell。

## 統一後的設計 token

文章頁目前對齊首頁語言，核心 token 應維持一致：

- `--paper`
- `--paper-2`
- `--panel`
- `--ink`
- `--muted`
- `--jade`
- `--jade-2`
- `--cinnabar`
- `--gold`
- `--river`
- `--line`
- `--shadow`
- `--r`
- `--r-sm`
- `--w`
- `--serif`
- `--mono`

如果首頁 token 有調整，`article-base.css` 要一起跟著改，不要讓文章頁自己分岔。

## 文章頁共同規則

1. `body` 需要有 `id="top"`。
2. 文章頁尾只保留內容，不要手寫一份固定 footer。
3. `回首頁 | Top` 由 `article-base.js` 統一補上。
4. traffic counter 由共用底座統一補上。
5. `page-overlay` 由共用底座統一處理，不要每篇重寫。
6. 圖卡如果有 SVG / PNG 下載需求，使用 `figure-actions`、`data-figure-name`、`copy-status` 這套共用互動。
7. 文章內容區盡量使用共用結構：
   - `page`
   - `main-column`
   - `hero`
   - `panel`
   - `toc`
   - `figure-card`
   - `callout`
   - `split`
   - `two-col`
   - `mini-card`

## 新增文章時怎麼做

- 直接引入：
  - `assets/css/article-base.css`
  - `assets/js/article-base.js`
- 不要再拷貝首頁或舊文章的整段 inline shell。
- 只寫文章內容本身，版型交給共用底座。
- 中英文版只需要切換 `lang` 與文案，不要再分裂出兩套視覺規則。

## 已知注意事項

- 少數圖表或內嵌 SVG 的局部樣式可以留在文章內，但只限於圖表本身。
- 不要把頁尾、overlay、traffic counter、Top 錨點再寫回文章 HTML。
- 若之後首頁版型再改，先同步檢查 `article-base.css`，避免文章頁跟首頁的視覺語言再次分岔。

## 一句話總結

**文章頁現在應該是「同一套設計 token + 同一套 shell + 不同內容」，而不是每篇文章各自長出一套版型。**
