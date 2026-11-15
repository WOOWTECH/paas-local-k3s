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
- `tools/gitea-push-mirrors.sh`   在 Gitea 上建立 6 個 push mirror（需 GitHub fine-grained PAT）
- `tools/images.txt`               要從 JCR 複製到 GHCR 的映像清單（digest 釘死）
- `tools/mirror-images.sh`         在筆電節點跑 skopeo Job（hostAliases 走 tailnet 到 JCR）
- `tools/mirror-charts.sh`         從 Gitea Helm registry 拉 chart 推到 oci://ghcr.io/woowtech/charts
- `values/paas-operator.lab.yaml`  operator Helm values（lab）
- `values/woow-odoo.platform.lab.yaml` 平台 Odoo Helm values（lab）
- `values/cloudflare-ha.lab.yaml`  lab tunnel connector values
- `jobs/platform-init.yaml`        平台 DB 一次性初始化 Job（chart 不做 fresh install）
- `addons/woow_paas_platform_lab/` overlay addon：隱藏 SH/SA、改 6 個範本的 chart／image 座標、local-path

## 執行順序（runbook）
0. 憑證就位（見下）。
1. `tools/gitea-push-mirrors.sh` → 6 個 GitHub repo 同步完成（看 `last_update`／`last_error`）。
2. `tools/mirror-images.sh` → 映像進 GHCR；`tools/mirror-charts.sh` → chart 進 GHCR。
3. 本機叢集：`kubectl --context default create ns paas-system`；建 GHCR pull secret `ghcr-registry`。
4. Cloudflare：用 CF token 建 tunnel `paas-lab`（API），取得 tunnel id／token；裝 `cloudflare-ha` chart（paas-app-bundle-cd 的 vendored chart）到 ns `paas-stg-cloudflare-system`。
5. `helm install paas-operator oci://ghcr.io/woowtech/charts/paas-operator --version 0.1.36 -n paas-system -f values/paas-operator.lab.yaml`。
6. `helm install paas-odoo-platform oci://ghcr.io/woowtech/charts/woow-odoo --version 0.2.27 -n paas-system -f values/woow-odoo.platform.lab.yaml --set replicas=0 --set cron.replicas=0`（只起 PG）。
7. `kubectl apply -f jobs/platform-init.yaml` → 建 DB、-i woow_paas_platform、預寫 upgrade_done、seed 參數。
8. 把 web／cron 拉到 1；overlay addon 掛進去 `-i woow_paas_platform_lab`。
9. 驗收：開 workspace → 裝 postgresql／n8n → 檢查 ns／quota／netpol／備份 CronJob／tunnel 路由 → 刪除 → PVC 標記。

## 需要的憑證（放 ~/woow_tech_credential/，chmod 600，不進 git）
- `github-mirror-pat.env`：`GITHUB_MIRROR_PAT=…`（fine-grained，只對上面 6 個 repo：Contents read/write；若 repo 含 .github/workflows 另加 Workflows write — 目前 6 個都沒有）
- `ghcr-pat.env`：`GHCR_PAT=…`（classic，read:packages + write:packages；GHCR 不吃 fine-grained）
- `jcr-readonly.env`：`JCR_USER=… JCR_PASS=…`（JCR 唯讀；建議另開 lab 帳號而不是 woow-prod-2）
- `cf-paas-lab.env`：`CF_API_TOKEN=…`（Account: Cloudflare Tunnel Edit；Zone woowtech.io: DNS Edit）
