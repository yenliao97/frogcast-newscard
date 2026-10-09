# frogcast-newscard

Taiwan Frogcast 外媒搬運的 5🐸 自動圖卡。

1. 雲端 routine `【Frogcast】Threads News` 建好 Threads／X 純文字草稿，判定 5🐸 時把卡片規格寫進 `queue/<Threads 草稿 id>.json` 並 push。
2. GitHub Actions（`.github/workflows/newscard.yml`）跑 `newscard.py process`：檢查規格 → 排版（固定素材，不現生圖）→ 量有沒有溢出 → 上傳 R2 → 圖掛進那兩則草稿 → 另建一則英文 IG 草稿 → 規格搬到 `done/`。
3. 任何一步失敗就整個停下、什麼都不改，草稿維持純文字；GitHub 寄失敗通知。

## 規格欄位

見 `examples/sc02.json`。`theme` 是 `art/library/` 的 12 個主題之一，`variant` 是 a 或 b；`kapa` 是 `art/kapa/` 的 8 個表情之一；字數上限在 `newscard.py` 的 `LIMITS`。

## 手動

- 驗金鑰：Actions → newscard → Run workflow → `selftest`
- 看版面：Actions → newscard → Run workflow → `render-example`，圖在該次執行的 Artifacts

## 金鑰（repo Secrets）

`R2_ACCOUNT_ID` · `R2_ACCESS_KEY_ID` · `R2_SECRET_ACCESS_KEY`（SONLA Cloudflare 帳號，只限 `hanna-media`）· `BUFFER_API_KEY`

## 素材來源

- `render/`：複製自 `~/Desktop/2.Areas/TW Frogcast/tools/carousel/`（2026-10-09）。改版型時兩邊都要改。
- `art/library/`：`~/ComfyUI-Shared/output/kapa/library/final/`
- `art/kapa/`：`~/Desktop/2.Areas/TW Frogcast/Frogs-transparent/`（妹妹的原圖去背，不修改）

之後搬到 Mac mini：同一支 `newscard.py` 在本機跑，觸發改成 n8n，停掉這支 workflow。
