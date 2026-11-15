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
- `tools/post-render-lab-addon.py` Helm post-renderer：把 overlay addon 以 ConfigMap 掛到 /opt/woow/addons/、所有平台工作負載避開筆電／TUF
- `values/paas-operator.lab.yaml`  operator Helm values（lab）
- `values/woow-odoo.platform.lab.yaml` 平台 Odoo Helm values（lab）
- `values/cloudflare-ha.lab.yaml`  lab tunnel connector values
- `jobs/platform-init.yaml`        平台 DB 一次性初始化 Job（chart 不做 fresh install）
- `addons/woow_paas_platform_lab/` overlay addon：隱藏 SH/SA、改 6 個範本的 chart／image 座標、local-path

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
9. 驗收：開 workspace → 裝 postgresql／n8n → 檢查 ns／quota／netpol／備份 CronJob／tunnel 路由 → 刪除 → PVC 標記。

## 憑證（都在 ~/woow_tech_credential/，chmod 600，不進 git）—— 2026-11-15 實際採用
- GitHub 寫入（push mirror 的 remote_password）與 GHCR 推／拉：**直接用這台機器 `gh auth token`**（classic，repo＋write:packages；使用者決定）。
  若改用小鑰匙：放 `github-mirror-pat.env`（GITHUB_MIRROR_PAT）／`ghcr-pat.env`（GHCR_PAT），腳本會優先採用。
- `jcr-readonly.env`：`JCR_USER`／`JCR_PASS` ＝ **正式站 tenant ns 的 `paas-registry` pull secret（woow-prod-2）**（使用者決定沿用）。
- `cf-paas-lab.env`：`CF_API_TOKEN`（使用者提供；可讀 account tunnels、zone DNS；**zone WAF rulesets 403** → operator 的 MCP 公網連通性檢查顯示 waf=permission_denied，6 範本不受影響）。
- `paas-lab-tunnel.env`：`TUNNEL_ID=7ff55c23-213e-4077-b823-a7e1744078b8`、`TUNNEL_TOKEN`（建 tunnel 時取得）。
- `paas-lab-platform.env`：OPERATOR_API_KEY、PLATFORM_ADMIN_PASSWORD、PLATFORM_PG_PASSWORD、PLATFORM_ODOO_PASSWORD、PLATFORM_MASTER_PASSWD（本機產生）。

## 已知問題與 lab 專屬調整（2026-11-15 實測）
- **TUF 節點的 pod 網路不通**：該節點上的 pod 連 CoreDNS 都逾時（叢集既有問題，需上機查 flannel／防火牆）。
  operator `config.tenantAvoidNodes` 讓租戶 pod 避開 TUF 與筆電；平台本身用 post-renderer 的 nodeAffinity 避開。
- **operator CPU**：kubectl apply 每次約 2.9 CPU 秒（本叢集 245 種 API 資源）；limits 1 核時建 namespace 34 秒 > 平台寫死的 30 秒 timeout。現為 3 核。
- **Bitnami postgresql／redis**：上游 is_active=False、映像只剩 `:latest`（浮動）；chart 自帶 NetworkPolicy 被 operator 的
  `paas-operator-tenant-netpol-guard` 擋 → overlay 關掉 chart NP；Redis 上游零方案 → overlay 補「Redis 月繳（lab）」。
- **訂閱日記帳**：fresh DB 沒設 → overlay `_lab_setup_billing` 自動補。
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
