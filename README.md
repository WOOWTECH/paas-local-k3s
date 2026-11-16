# paas-local-k3s — 本機 k3s 的 PaaS 控制面（WOOW PaaS 複本）

目的：把 woow-k3s 的 PaaS Odoo 必要套件（平台 Odoo + paas-operator + 入口）建在本機 k3s（kube context `default`），
來源一律是 GitHub（Gitea push mirror → GitHub repo；映像／chart → ghcr.io/woowtech）。
Security Access／Home Connect 隱藏（overlay addon）。研究報告：https://claude.ai/artifact/Fw2PVbJMFRUUjFPqQWYc9X

## 2026-11-15 決策（使用者）
1. 來源 = GitHub：Gitea 用 push mirror 同步到 GitHub（private），不改 Gitea 程式。
2. 鏡像 6 個 repo：odoo-addons/woow_paas_platform → odoo-addon-woow-paas-platform（既有）、woow-paas-charts、paas-odoo-ci、paas-app-bundle-cd、cc/woowprd → woowprd、woow-machines-operator。
3. 映像全部從 JCR 原樣複製到 ghcr.io/woowtech（skopeo，--preserve-digests），不在 GitHub build。
4. 平台 DB 全新安裝（fresh install）。
5. 對外沿用 Cloudflare Tunnel，直接用 woowtech.io 根域；lab 另開一條 tunnel。
6. 第一階段範本 6 個：postgresql、redis、n8n、odoo、litellm、emqx。

## 本 repo 的角色
鏡像 repo 是「強制推送的鏡像」，GitHub 端不得有自己的 commit；所有本機差異（values、init Job、overlay addon、工具）都放這裡。

## 目錄
- `tools/gitea-push-mirrors.sh`   在 Gitea 上建立 6 個 push mirror（GitHub 寫入權預設取 `gh auth token`）
- `tools/images.txt`               要從 JCR 複製到 GHCR 的映像清單（digest 釘死）
- `tools/mirror-images.sh`         在筆電節點跑 skopeo Job（hostAliases 走 tailnet 到 JCR）
- `tools/mirror-charts.sh`         從 Gitea Helm registry 拉 chart 推到 oci://ghcr.io/woowtech/charts
- `tools/post-render-lab-addon.py` Helm post-renderer：把 `addons/` 底下每個 addon 以 ConfigMap 掛到 /opt/woow/addons/、所有平台工作負載避開筆電／TUF
- `tools/lab_addons.py`           addon 掛載規則的唯一來源（哪些 addon、ConfigMap／volume 名稱、key 規則、二進位檔走 binaryData、`lab-extra-modules.txt`）
- `lab-extra-modules.txt`         每次 `tools/lab-overlay-update.sh` 都會 `-i` 的模組（已安裝的會跳過）
- `values/paas-operator.lab.yaml`  operator Helm values（lab）
- `values/woow-odoo.platform.lab.yaml` 平台 Odoo Helm values（lab）
- `values/cloudflare-ha.lab.yaml`  lab tunnel connector values
- `jobs/platform-init.yaml`        平台 DB 一次性初始化 Job（chart 不做 fresh install）
- `addons/woow_paas_platform_lab/` overlay addon：隱藏 SH/SA、改 6 個範本的 chart／image 座標、local-path
- `addons/woow_service_hub/`      vendored：Gitea `mirror-internal/Woow_odoo_saas_management` 的 `woow_service_hub`（commit 56efe98），平台映像裡沒有

## 執行順序（runbook）
0. 憑證就位（見下）。
1. `tools/gitea-push-mirrors.sh` → 6 個 GitHub repo 同步完成（看 `last_update`／`last_error`；之後 `gh repo edit --default-branch` 對齊 Gitea 預設分支）。
2. `tools/mirror-images.sh` → 映像進 GHCR（skopeo Job 在筆電節點、走 tailnet；約 1.5 MB/s）；`tools/mirror-charts.sh` → chart 進 GHCR。
3. 本機叢集：ns `paas-system`、`paas-stg-cloudflare-system`；Secrets：`ghcr-registry`（docker-registry）、`paas-operator-secret/api-key`、
   `paas-operator-registry/registry-password`、`paas-operator-cloudflare/cloudflare-api-token`、`paas-platform-lab-admin/admin-password`。
   平台三把密鑰寫在 gitignored 的 `values/secrets.platform.lab.yaml`（credentials.postgresPassword／odooPassword／adminPasswd，各 ≥8 字）。
4. Cloudflare：API 建 tunnel `paas-lab`（`config_src=cloudflare`），存 `~/woow_tech_credential/paas-lab-tunnel.env`（TUNNEL_ID／TUNNEL_TOKEN）；
   tunnel 設定 ingress：`paas-lab.woowtech.io → http://traefik.kube-system.svc.cluster.local:80`＋`http_status:404`；DNS CNAME `paas-lab` → `<tunnel>.cfargotunnel.com`（proxied）。
   connector：`helm upgrade --install cloudflare-tunnel-ha-lab <paas-app-bundle-cd>/cloudflare-ha-stg/chart -n paas-stg-cloudflare-system -f values/cloudflare-ha.lab.yaml --set cloudflare.tunnel_token=…`。
5. `helm upgrade --install paas-operator oci://ghcr.io/woowtech/charts/paas-operator --version 0.1.36 -n paas-system -f values/paas-operator.lab.yaml --wait`。
6. `helm upgrade --install paas-odoo-platform oci://ghcr.io/woowtech/charts/woow-odoo --version 0.2.27 -n paas-system -f values/woow-odoo.platform.lab.yaml -f values/secrets.platform.lab.yaml --set replicas=0 --set cron.replicas=0 --post-renderer tools/post-render-lab-addon.py`
   ⚠ 這一步**不要加 `--wait`**：local-path 是 WaitForFirstConsumer，web 0 副本時 `-data`／`-backup` PVC 會一直 Pending，--wait 會等到超時並把 release 標成 failed（資源其實都建好了；下一次 upgrade 會修正狀態）。
7. `python3 tools/with-lab-addon-items.py jobs/platform-init.yaml | kubectl --context default apply -f -` → 建 DB、`-i base,web,woow_paas_platform,woow_paas_platform_lab`、預寫 upgrade_done、seed 參數、設 admin 密碼（約 15 分）。
   Job 是 `-data` PVC 的第一個消費者，決定 PV 綁哪個節點（已加 nodeAffinity 避開筆電／TUF）。
8. 先手動跑一次備份讓備份 PVC 綁定：`kubectl --context default -n paas-system create job --from=cronjob/paas-odoo-platform-backup paas-odoo-platform-backup-manual-1`；
   再跑第 6 步的指令但不帶 `--set replicas=0 --set cron.replicas=0`（可加 `--wait`）→ web／cron 各 1 副本。
   之後 overlay addon 有改：一律用 `tools/lab-overlay-update.sh`（先 `-u` 再滾動；順序反了 upgrade-gate 會讓 web 起不來）。
9. 重建時第 8 步之後再跑一次 `tools/lab-overlay-update.sh`：它會 `-i` `lab-extra-modules.txt` 的模組（課程、線上客服、LINE、文件、服務中心），再跑 `site/build_site.py`、`site/patch_*.py` 建首頁。
9. 驗收：開 workspace → 裝 postgresql／n8n → 檢查 ns／quota／netpol／備份 CronJob／tunnel 路由 → 刪除 → PVC 標記。

## 憑證（都在 ~/woow_tech_credential/，chmod 600，不進 git）—— 2026-11-15 實際採用
- GitHub 寫入（push mirror 的 remote_password）與 GHCR 推／拉：**直接用這台機器 `gh auth token`**（classic，repo＋write:packages；使用者決定）。
  若改用小鑰匙：放 `github-mirror-pat.env`（GITHUB_MIRROR_PAT）／`ghcr-pat.env`（GHCR_PAT），腳本會優先採用。
- `jcr-readonly.env`：`JCR_USER`／`JCR_PASS` ＝ **正式站 tenant ns 的 `paas-registry` pull secret（woow-prod-2）**（使用者決定沿用）。
- `cf-paas-lab.env`：`CF_API_TOKEN`（使用者提供；可讀 account tunnels、zone DNS；**zone WAF rulesets 403** → operator 的 MCP 公網連通性檢查顯示 waf=permission_denied，6 範本不受影響）。
- `paas-lab-tunnel.env`：`TUNNEL_ID=7ff55c23-213e-4077-b823-a7e1744078b8`、`TUNNEL_TOKEN`（建 tunnel 時取得）。
- `paas-lab-platform.env`：OPERATOR_API_KEY、PLATFORM_ADMIN_PASSWORD、PLATFORM_PG_PASSWORD、PLATFORM_ODOO_PASSWORD、PLATFORM_MASTER_PASSWD（本機產生）。

## 第二批：agent 範本（pi-agent／hermes-agent／open-design／omnigent）
使用者 2026-11-15 晚要求上架並實測。做法與第一批相同，另外有這些 lab 專屬調整：
- 映像：`tools/images-agents.txt`（`bash tools/mirror-images.sh tools/images-agents.txt`）。omnigent 兩顆映像 GHCR 上已有同 digest 的公開 package，不用複製。
- chart：`tools/mirror-charts.sh` 已含四支。omnigent 推到私有 `oci://ghcr.io/woowtech/paas-charts`（`charts/omnigent` 是別的專案的公開 package）；
  hermes-agent 的 `helm push` 會被 GHCR 回 500（說明含大量中文），改用 `tools/oci-push-chart-nodesc.py`（tgz 原封不動）。
- 方案：pi-agent、omnigent 方案 8GB → 3GB（overlay `_lab_setup_plans`；上游方案 noupdate=1，XML 覆寫在 -u 時會被略過）。
- 資源：open-design、hermes-agent requests 1Gi／limits 3Gi（overlay `TEMPLATE_VALUE_FIXES`）。
- 叢集參數：`woow_paas_platform.apiserver_cidrs = 10.43.0.1/32,192.168.2.10/32`（console／omnigent server 連 API 要 node /32）。
- operator 釘筆電：小節點（Pentium N3700）建新 namespace 38 秒，超過平台寫死的 30 秒；筆電 8.7 秒。
- LLM：四個 agent 開通都不需要金鑰；要實際叫模型，租戶自己在服務裡填 OpenRouter／Anthropic 等金鑰，或在同工作區開 LiteLLM（平台會自動把網址注入 pi-agent／open-design／hermes）。

## 第三批：其餘正式站範本（13 個）＋停權頁
- 映像 `tools/images-rest.txt`（15 顆，約 4.4GiB）；chart 7 支（`tools/mirror-charts.sh` 第三批）。
- overlay 18.0.1.0.7–0.9：13 個上架；nextcloud 的 postgresql.image 改 ghcr；code-server／nextcloud 方案 → 3GB；
  haos 跑不起來（HAOS 32GiB 虛擬磁碟，小節點最多剩 31GiB）→ 11-16 依使用者指示移除：範本停用＋隱藏（overlay `LAB_REMOVED_SLUGS`，
  API 也開不出來）、殘留 DataVolume 已刪、`images-rest.txt`／`mirror-charts.sh` 已拿掉；GHCR 上的 haos 映像與 chart 保留。
- 正式站也隱藏的 6 個維持隱藏（原因查自 seed 註解與 Gitea PR）：mcp-odoo-manage（10-06 停售，只留 mcp-odoo；映像停在舊版）、
  mcp-k8s 與 mcp-vk（10-09 下架 #1624；mcp-vk 另於 11-14 #2431／#2432 整個移除，下版平台映像就沒有）、
  mcp-opendesign（10-15 內建進 Open Design #1741；本機 Open Design 的 /mcp-admin/ 可用）、
  ha-paas（Woow App 的免費雲端 HA，由 App 呼叫 /api/ha-paas/provision 開通，兩層都隱藏；正式環境 0、staging 2）、
  ha-full-apporo（9-25 封存，展示機改走 apporo.ai）。這 6 個的映像都沒有複製。
- `infra/suspended-page/`：停權說明頁（operator 停權時把路由改指這裡）。
- MCP 伺服器的管理員密碼存在 config.json（平台只能重設、不能自訂）→ 改在 MCP Admin 內 `PUT /api/settings/admin_password {"value": …}`（要 If-Match revision）；
  MCP Headscale 的管理介面沒有改密碼功能。Nextcloud 密碼由 app 自管（occ user:resetpassword；預設密碼政策最短 10 字）。
- Tailscale 要用平台的「VPN 配對」（`/vpn/options` → `/vpn/pair`）綁同工作區 Headscale，手動填 authKey 不會注入登入伺服器。

## 第四批：平台層元件
- **停權說明頁**（`infra/suspended-page/`）：已搬。
- **Woow MCP gateway**（平台自己的 MCP，`https://paas-lab.woowtech.io/mcp/woow`）：已搬。
  chart `woow-mcp-gateway 0.2.0`（GHCR）、映像 `tools/images-platform.txt`、`values/woow-mcp-gateway.lab.yaml`
  （chart 沒有 affinity 參數 → `--post-renderer tools/post-render-avoid-nodes.py`）、`infra/woow-mcp-gateway/`（三條 path 的 Ingress、gateway→Odoo 的 NetworkPolicy）、
  Secret `woow-mcp-gateway`＋平台 `webOnlyExtraEnv: WOOW_MCP_GATEWAY_SECRET`、overlay 打開 `api_token_enabled`（寫入開關維持關）。
  只有「租戶帳號」（portal、share=True）能建 API token；測試帳號 `lab-tenant`。
  ⚠ 這版平台映像沒有 `/.well-known/oauth-authorization-server`（正式站較新的 .215 才有）→ claude.ai 這類走 OAuth 的 MCP client 要等平台映像更新；用 API token 的 client 可用。
- **operator／paas-system 網路白名單**（`infra/netpol/`）：已搬（operator 只收平台 Odoo；paas-system 預設擋 ingress）。
- **不搬**：自訂網域 gateway（要動 woowtech.io zone 的 Cloudflare for SaaS 設定，跟正式站共用，會影響正式站自訂網域）；
  agent runtime（要 LLM 金鑰＋operator 從受 Cloudflare Access 保護的 Gitea 抓 chart）；node-mss-clamp（只有 HAOS 需要，HAOS 已因磁碟隱藏）。

## 首頁：woowtech Cloud 一頁式介紹（2026-11-16）
- overlay 18.0.1.0.12 加相依 `website`（平台裝了 Odoo 網站模組；正式站平台本來就有）。網站內容與修改方式見 `site/README.md`。

## 第五批：內部用 app（2026-11-16，overlay 18.0.1.0.15）
- 使用者要裝：原生「課程」`website_slides`、「線上客服」`im_livechat`（網站已裝 → 自動帶 `website_livechat`）；woowtech 自製
  LINE 全套裝 `woow_line_base`＋`woow_odoo_line_liff`＋`woow_odoo_livechat_line`、文件檔案 `woow_document_management`、
  SaaS 線上服務管理＝服務中心 `woow_service_hub`（依賴 hr → 一併裝「員工」）。清單在 `lab-extra-modules.txt`。
- 前五個都在平台映像（paas-odoo-official 20261114.0636）的 /opt/woow/addons；`woow_service_hub` 不在，從 Gitea 鏡像 vendored 進
  `addons/woow_service_hub/`，跟 overlay 一樣用 ConfigMap 掛進去（工具改成支援多個 addon，規則在 `tools/lab_addons.py`）。
- 「庫存」不能解除安裝：`woow_paas_platform` → `ecpay_invoice_tw` → `stock`，解除會連平台一起移除 → 改成藏選單（`LAB_HIDDEN_MENUS`）。
- 網站：線上客服**不**在首頁／登入頁顯示聊天按鈕（網站的即時聊天頻道清空）；「課程」放進首頁上方選單（`site/patch_02_apps.py`）。
- LINE 模組裝好還要 LINE 官方帳號的 Channel 設定（Messaging API／LIFF）才會動。

## 已知問題與 lab 專屬調整（2026-11-15 實測）
- **TUF 節點的 pod 網路不通**：該節點上的 pod 連 CoreDNS 都逾時（叢集既有問題，需上機查 flannel／防火牆）。
  operator `config.tenantAvoidNodes` 讓租戶 pod 避開 TUF 與筆電；平台本身用 post-renderer 的 nodeAffinity 避開。
- **operator CPU**：kubectl apply 每次約 2.9 CPU 秒（本叢集 245 種 API 資源）；limits 1 核時建 namespace 34 秒 > 平台寫死的 30 秒 timeout。現為 3 核。
- **Bitnami postgresql／redis**：上游 is_active=False、映像只剩 `:latest`（浮動）；chart 自帶 NetworkPolicy 被 operator 的
  `paas-operator-tenant-netpol-guard` 擋 → overlay 關掉 chart NP；Redis 上游零方案 → overlay 補「Redis 月繳（lab）」。
- **訂閱日記帳**：fresh DB 沒設 → overlay `_lab_setup_billing` 自動補。
- **內部使用、不收費（使用者 2026-11-16）**：overlay 18.0.1.0.13 起
  - 後端 `_lab_disable_charging`（每次 -u 再套一次）：所有 `woow.subscription.plan` 價格 0、試用 0 → 開通／換方案／續訂都是
    平台原生的「0 元一期」（不碰錢包、不開電子發票、不會欠款）；停用排程：每日計費、合約到期（模組預設就關）、綠界定期扣款、
    續訂前餘額不足提醒、計費靜默告警。保留 `ir_cron_subscription_lifecycle`（已刪除服務的保留與清除靠它）。
  - 前台 `static/src/paas/lab_no_billing.{xml,js}`：拿掉頁首 CREDITS、頭像選單的點數與發票、側欄「財務」三項、手機底欄帳單、
    總覽帳單卡、市集與建服務頁的價格、方案卡價格與月繳／年繳切換、服務總覽的價格／試用／付款日、略過試用、換方案的退點說明、
    續訂的金額、付款方式、發票偏好；帳單類網址一律導回總覽；舊的試用訂閱徽章顯示成「使用中」。只是外觀，後端 API 還在。
  - 原本的價格與試用長度存在 `ir.config_parameter` `woow_paas_platform_lab.plan_terms_before_charging_off`（JSON：plan id →
    [price, trial_length, trial_unit]）。**要恢復收費**：先拿掉 `lab_overrides.xml` 的 `_lab_disable_charging` 與 manifest 的
    `lab_no_billing.*`、跑 `tools/lab-overlay-update.sh`，再用 odoo shell 照快照寫回方案、重新打開需要的排程。
  - **18.0.1.0.14（同日，使用者：「相關的都隱藏，因為是內部使用」）**：
    - 方案名稱拿掉「訂閱／月繳／年繳」（`_lab_internal_plan_names`；例「n8n雲端訂閱服務（6人）+5 存取席位 月繳」→「n8n雲端服務（6人）+5 存取席位」），
      原名存在 `woow_paas_platform_lab.plan_names_before_internal`（JSON：plan id → 原名）。overlay 自己的 Redis 方案直接改成「Redis（lab）」0 元不試用。
    - 後台（`_lab_hide_billing_backoffice`）：藏「發票」「銷售」兩個 app、Woow PaaS 的「帳務事件」「綁卡驗證授權取消」、AI 模型的五個額度選單；
      解除聯絡人「動作」裡的 Grant Wallet Credits。恢復＝把 `LAB_HIDDEN_MENUS` 的選單設回 active、action 綁回 res.partner。
    - 前台再補：服務卡的訂閱徽章、服務頁的「訂閱已取消／請續訂」橫幅、舊試用訂閱換方案時的「結束試用、開始計費」關卡、
      通知中心的帳務通知（trial_ending、renewal_low_balance、invoice_unpaid、wallet_activity、llm_*）。
  - 已存在的 17 個測試訂閱價格在開通時就凍結（引擎不准改），但每日計費關著，不會扣款也不會因此停權。
  - 11-16 早先給的贈點（Administrator 1,000,000＝WT00000001、Lab Tenant 100,000＝WT00000002）還在錢包裡，只是前台看不到、用不到。
- **公開網址**：租戶服務是 `paas-cs-<ws8>-<svc8>.woowtech.io`，跟正式站同一層網域，名稱不會撞（帶亂數），但肉眼分不出是 lab。

## 執行紀錄
- 2026-11-15 15:12 push mirror 6 個建立並同步成功（head SHA／tag 數與 Gitea 一致；GitHub 預設分支已對齊）。
- 2026-11-15 15:13 chart 5 支推上 ghcr（woow-odoo 0.2.27／0.2.26、paas-operator 0.1.36、litellm 0.3.16、emqx 0.1.11）。
- 2026-11-15 15:15 skopeo Job 開跑（第一次失敗：skopeo 不接受 tag+digest 並存 → 改 repo@digest）。
- 2026-11-15 15:20 tunnel paas-lab 建立、connector 上線（healthy，4 條連線）、`https://paas-lab.woowtech.io/` 已通到本機 traefik（404 = 尚無 Ingress）。
- 2026-11-15 15:27 operator 0.1.36 deployed（woowtechcluster7；F6 guard OK）。
- 2026-11-15 15:31 平台 release 安裝（PG 在 woowtechcluster2；--wait 因 PVC Pending 超時 → 狀態 failed，見第 6 步註）。
- 2026-11-15 15:40 platform-init Job 開跑（woowtechcluster4，`-data` PV 綁在該節點）。
- 2026-11-15 16:05 platform-init 完成（80 模組、overlay 套 29 個範本、marker 與 admin 寫入）；web／cron 起來，公開網址 200。
- 2026-11-15 16:17 第一次手動備份成功（backup PVC 因此綁定，helm --wait 才會過）。
- 2026-11-15 16:19–16:50 驗收：開服務依序踩到 訂閱日記帳未設、operator 30 秒逾時、Docker Hub IPv6 偶發、Bitnami NetworkPolicy 被 guard 擋；逐一修掉後 PostgreSQL 通過（lab-pg-4 留著當樣本）。
- 2026-11-15 16:39 overlay 改版號後先滾動 web → upgrade-gate 擋（DB 版本落後）→ web 停約 2 分；已改 `tools/lab-overlay-update.sh` 先 -u 再滾動。
- 2026-11-15 16:54–17:20 n8n 通過（公開網址 200、刪除後 tunnel 規則／DNS／release 清掉、PVC 標 orphaned）；Redis 通過；Odoo 第一次排到 TUF（pod 網路壞）失敗 → tenantAvoidNodes 後通過（公開網址 200）。
- 2026-11-15 17:30 工作區 1 的 PVC 配額（10）被保留期內的測試資料吃滿 → LiteLLM／EMQX 改在工作區 2（lab-acceptance-2）測。
- 2026-11-15 17:35–17:45 LiteLLM、EMQX 在工作區 2 通過（公開網址皆 200）；6 個範本全部通過。
- 2026-11-15 17:45 overlay 18.0.1.0.4（藏「探索更多服務」與工作區列表頁的兩張卡片）套用；瀏覽器以臨時帳號實看兩頁只剩「雲端服務」，臨時帳號已封存。
- 現況：工作區 1 `lab-acceptance` 留一個 PostgreSQL（lab-pg-4）當樣本；工作區 2 `lab-acceptance-2` 為空；刪除的測試服務 PVC 依保留期（1／7 天）由 operator 自動清。
- 2026-11-15 18:00–19:40 第二批 agent 範本：映像 5.1GiB 從 JCR 複製（約 50 分）；overlay 18.0.1.0.6；operator 改釘筆電。
  在工作區 4 `lab-agents` 實測全部通過並保留：Omnigent（約 5 分；accounts 登入、錯誤密碼 401、server SA 只能在自己 ns 建 Job）、
  Pi agent（約 12 分；匿名 401、管理員登入 200「Pi Web」）、Hermes（約 9 分；表單登入、console 200）、Open Design（約 12 分；匿名 401、登入 200、console 200）。
  ⚠ 平台「重設管理員密碼」會讓 Pi agent 等 pod 重啟，重啟期間再按一次會被拒（服務正在完成更新）。
- 2026-11-15 20:10–21:30 第三批：7 個 MCP、Headscale、Tailscale、Nextcloud、Home Assistant 完整版、Code Server 全部開通並保留；
  MCP Odoo 端到端（連本機平台 Odoo、MCP 協定列 41 個工具、search_records 查出 23 個範本）；Tailscale 經 VPN 配對加入同工作區 Headscale（節點上線 100.64.0.1）；
  HA 完成初始設定；HAOS 磁碟不足 → 隱藏。測試用密碼依使用者要求設為同一組簡單密碼（MCP Headscale 除外）。
- 2026-11-15 22:30–23:30 第四批：停權頁、Woow MCP gateway（租戶 token → MCP initialize／tools/list 5 個工具／list_workspaces 只回自己的工作區／撤銷後 401）、
  paas-netpol（無關 pod 連不到 operator、平台照常）；overlay 18.0.1.0.10。
- 2026-11-16 HAOS 移除（overlay 18.0.1.0.11；殘留 DataVolume 刪除、cluster5 釋出 32GiB 的 PV）；報告改正正式站使用數（排除 staging）。\n- 2026-11-16 平台裝 website（overlay 18.0.1.0.12），建立 woowtech Cloud 一頁式首頁（`site/`）；匿名／手機／登入頁／編輯器都實測過。\n
- 2026-11-16 用平台贈點精靈給 Administrator 1,000,000 點、Lab Tenant 100,000 點（內部使用）；確認 lab 計費排程本來就是關的、試用到期不會停權。
- 2026-11-16 內部使用不收費：overlay 18.0.1.0.13（方案 0 元＋不試用＋停用 5 個扣款相關排程；前台隱藏點數／儲值／帳單／價格）。
- 2026-11-16 overlay 18.0.1.0.14：方案名稱去計費字樣、後台帳務選單與贈點動作隱藏、前台訂閱徽章／續訂橫幅／帳務通知隱藏；兩帳號 24 頁＋通知面板驗收乾淨。
