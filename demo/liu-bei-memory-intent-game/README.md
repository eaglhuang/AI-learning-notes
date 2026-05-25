# 三國人物互動劇場 Demo

這個資料夾可直接部署到 GitHub Pages 靜態站點，預設頁面支援在頁內切換劉備、關羽、張飛三位主角。

預設頁面：

`/demo/liu-bei-memory-intent-game/index.html`

若要接本機 `npc-brain`，可用 query string 指定主角與 API：

`/demo/liu-bei-memory-intent-game/index.html?generalId=liu-bei&apiBase=http://127.0.0.1:8000`

`/demo/liu-bei-memory-intent-game/index.html?generalId=guan-yu&apiBase=http://127.0.0.1:8000`

`/demo/liu-bei-memory-intent-game/index.html?generalId=zhang-fei&apiBase=http://127.0.0.1:8000`

若未提供 `apiBase` 或 API 無法連線，頁面會自動退回示範資料模式。
