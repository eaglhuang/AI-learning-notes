# ATM Petri 培養皿 — Atom Behavior Interactive Theatre

把 ATM 框架的 12 種原子行為（split / merge / dedup-merge / sweep / evolve / expire / polymorphize / infect / atomize / anchorize / promote / compose）視覺化為**培養皿中的生物事件**。玩家扮演 ATM 巡查員，反應 demand-police findings，選對 behavior 讓代碼健康指數上升。

預設頁面：`/demo/atm-petri-dish/index.html`

## 對應文件

主規格：`docs/ai_atomic_framework/原子行為參考手冊.md`（doc_other_0045）

每個 finding 規則、behavior 動畫、tier 轉換都可以在主規格中找到對應段落。遊戲內每顆 capsule、anchor、demand-police finding 都來自 3KLife 真實的 `atomic_workbench/`，bake 成 snapshot 包進 `data/*.json`。

## 玩法

1. **Tutorial（4 個 step，~3 分鐘）**
   - Step 1: `orphan-capsule` → **🫧 錨點化**
   - Step 2: `duplicate-fingerprint` → **🔬 合併去重**
   - Step 3: `family-promotion-threshold` → **🧬 多形化**
   - Step 4: `ready-for-governed` → **⬆️ 晉升**
2. **Sandbox 自由模式**：每 8 秒隨機觸發一個 finding，從 8 種規則中抽。沒有時限，慢慢練手感。

正確 behavior：+5 健康度 + 成功 toast。錯誤 behavior：-8 健康度 + 教學氣泡告訴你為什麼不對 + 正確答案。

## 本機跑法

純靜態，不需要 build step。snapshot 是 `fetch('./data/*.json')` 載入相對路徑，**需要一個本機 server**（直接雙開 `index.html` 會被 browser CORS 擋）：

```bash
# 從 3KLife repo root：
python -m http.server 8000 --directory temp_workspace/AI-learning-notes
# 然後開 http://localhost:8000/demo/atm-petri-dish/
```

如果 snapshot 載入失敗，遊戲會自動 fallback 到內建的 5 顆 hardcoded demo capsule，仍可玩。

## 重生 snapshot

`data/*.json` 是某時點的 ATM 快照。如果 `atomic_workbench/capsules/` 改了，重跑：

```bash
# 1. 重新跑 demand-police 報告
node tools_node/atm-atomize.js demand-police --json
# 2. 重建 demo 用的 3 份 snapshot（會讀上一步的報告 + 12 個指定 capsule + 1 個 anchor）
node temp_workspace/AI-learning-notes/demo/atm-petri-dish/build-snapshots.js
```

要換不同 capsule 入鏡，編輯 `build-snapshots.js` 的 `SELECTED_CAPSULES` 陣列即可。

## 技術選擇

- 單檔 `index.html`（inline css + js），無 build / 無 npm 依賴，跟 `demo/liu-bei-memory-intent-game/` 相同模式
- HTML5 Canvas 2D 畫培養皿；DOM 畫 finding 面板、behavior dock、頂部 health gauge
- 重用 AI-learning-notes 首頁的設計 token（jade / cinnabar / gold / paper / ink）
- 細胞 / 膜形變是 canvas 內以 sin / cos 即時運算（沒有預錄 GIF）
- 粒子上限 220 個；finding 同時最多 3 個
- DPR-aware canvas，retina 螢幕清晰

## 設計理念

ATM 框架的原子行為文件密度極高（12 種行為 × 8 條 demand-police 規則 × 4 層治理），純文字難以建立直覺。把它做成**活生態系**：

- **Code = 培養皿**
- **Capsule = 細胞**（tier 越高顏色越亮 → grey → jade → gold → cinnabar）
- **Anchor = 細胞膜**（半透明 morph blob）
- **Demand-police = 白血球巡邏**（finding 警示）
- **Behavior = 治療事件**（split=分裂、merge=融合、polymorphize=template化、sweep=淡出退役）

正確的 behavior 序列會讓培養皿從一片亂跳到健康有序；錯的選擇會把細胞推向 deprecated / expired。玩家內化的不是名詞，而是**「在這種情況下該觸發哪種行為」**的直覺。

## Follow-up

延伸計畫見 `docs/agent-briefs/tasks/WEB/`：
- TASK-WEB-0002：抽出 inline JS 到 `petri.js`，納入 `atm-atomize` includeGlobs
- TASK-WEB-0003：`?live=1` 模式，fetch 同 repo 即時 registry
- TASK-WEB-0004：擴增 8-10 關教學模式（涵蓋 sweep / expire / infect / sealed-split-attempt）
- TASK-WEB-0005：vs AI 對戰模式（兩個 dish 並列）
