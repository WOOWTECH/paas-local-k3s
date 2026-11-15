# woowtech Cloud 一頁式首頁（本機平台 https://paas-lab.woowtech.io/）

使用者 2026-11-16 決定：放在本機平台首頁、寫給公司內部同仁（主按鈕「登入平台」、不放價格）、系統名稱 **woowtech Cloud**、
中文為主英文點綴（單一語言版本）。品牌依據是使用者提供的 woowtech Brand Prompt Library v2。

## 之後怎麼改（重要）
- 一律用 Odoo **網站編輯器**：admin 登入 → 網站 → 右上「編輯」。文字、圖片、按鈕、區塊順序、增刪區塊都在這裡改。
- 字型、配色、按鈕圓角：編輯器「設計主題」分頁。
- 品牌 CSS（毛玻璃卡、圖示磚、勾選清單、20px 圓角…）：開發者模式下「HTML／SCSS 編輯器」的 `user_custom_rules.scss`
  （內容等於本目錄的 `custom_rules.scss`）。
- 中文字型 Noto Sans TC 與手寫字 Yellowtail 從「網站 → 設定 → 自訂程式碼（<head>）」載入
  （Odoo 只會載入有指定給字型欄位的 Google 字型）。
- `build_site.py` 是**一次性**建站腳本；首頁已經有內容時會拒絕執行，避免蓋掉編輯。要整頁重建才加 `WW_FORCE=1`。
  `patch_01_fonts_security.py` 是建好之後的第一次修正（字型、「安全」區塊、頁首搜尋），已套用。

## 頁面結構（全部是 Odoo 內建 snippet）
| 區塊 | snippet | 內容 |
|---|---|---|
| 首屏 | s_cover | 毛玻璃卡疊在品牌壓紋玻璃照片上；「需要的服務，幾分鐘就開好」；登入平台／看看有哪些服務 |
| 系統介紹 #intro | s_text_image | 一個工作區放進團隊要用的服務；平台實際畫面（資源配額＋執行中的服務） |
| 服務範本 #templates | s_cards_soft | 4 類 22 種：資料庫與基本服務 7、AI 與開發工具 5、MCP 伺服器 7、VPN 與智慧家庭 3 |
| 怎麼開始 #start | s_key_benefits | 登入平台 → 建立工作區 → 從範本開服務 |
| 數字 | s_numbers | 22 種範本、2–12 分鐘開好（實測）、刪除後 7 天才清除 |
| 安全與資料 #security | s_features_grid | 工作區隔離、服務都要登入、刪掉不會馬上消失、平台每天備份 |
| 行動呼籲 | s_call_to_action | 開你的第一個服務 → 登入平台 |

頁首：woowtech 藍色標誌、四個段落錨點、「登入平台」按鈕（關掉登入連結、示範電話、搜尋）。
頁尾：品牌簡介、快速連結、需要協助；版權 WOOW Technology Co., Ltd.；不顯示「由 Odoo 驅動」。

## 素材（assets/）
`logo-lockup-*.svg`、`logo-symbol-blue.svg`、`bg-frosted-fluted.jpg` 來自品牌包；`favicon.png` 由藍色符號轉出；
`mdi-*.svg` 是 Material Design Icons 7.4.47（品牌指定圖示集）改成品牌藍；`product-workspace.png` 是平台畫面截圖。
