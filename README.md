# AI Learning Notes

這是 Eagl Huang 的 AI 學習與工程實作筆記站，使用 GitHub Pages 發布。

網站首頁：<https://eaglhuang.github.io/AI-learning-notes/>

## 目前內容

- 首頁：`index.html`
- 文章列表：`articles/index.html`
- 首篇長文：`harness_engineering_article_public.html`
- 共用樣式：`assets/css/site.css`
- 文章共用底座：`assets/css/article-base.css`、`assets/js/article-base.js`

## 發布方式

這個 repo 使用純靜態 HTML/CSS，不需要 build step。只要 GitHub Pages 設定為從 `main` branch 的 root 發布，推送後即可更新網站。

新增技術文章時，請優先沿用 `article-base`，讓 footer、Top 錨點、traffic counter、overlay 與下載互動保持一致。
