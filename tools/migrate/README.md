# 本機 k3s 既有部署 → PaaS 管理（搬遷工具）

PaaS 沒有「原地接管」：平台只認自己在 `paas-ws-lab-*` 底下用 `svc-<8hex>` 裝的 release（operator 的 namespace 前綴守門）。
所以搬一個服務＝**用平台自己的建立流程開新服務 → 停新舊兩邊 → 把資料磁碟內容整包搬過去 → 開新的、驗收**，舊的先縮到 0、資料磁碟留著（退回用）。

## 步驟（以 pi5 為例，2026-11-16）
1. 建服務：`create_service_pi5.py`（odoo shell）。走 `service_ops.plan_create` / `write_create`（跟網站同一條），
   同一個交易裡把管理員 helm_values 補上（nodeSelector、omnigentHost 等），commit 後才由「Deploy Pending」cron 安裝。
   - 先 `DRY=1` 試算（會回捲），再 `DRY=0`；一次性密碼寫到 pod 的 `OUT_SECRET` 再複製到 `~/woow_tech_credential/`（不印出）。
   - 映像大的先在目標節點預拉（小主機從 GHCR 約 3.4 MB/s，pi-agent 1.75GiB 要 8.5 分；否則平台可能判逾時）。
2. 資源不夠時改 helm_values 再走平台 Redeploy：`pi5_requests_1gi.py`。
   pi-agent 的方案規格只在建立時套一次（`_plan_spec_paths` 標 `existing: False`），之後以服務自己的 helm_values 為準，不會被改回。
3. 停新舊兩邊（`kubectl scale --replicas=0`）。平台的「running 服務 workload 檢查」每 10 分鐘一次、**不改 state**，只掛提醒、恢復後自動清掉。
4. 搬資料：接收端 `pi5-receiver.yaml`（目標節點、hostNetwork、root、hostPath 掛 local-path 的資料夾），
   傳送端 `pi5-sender.yaml`（來源節點、hostNetwork、root、唯讀掛舊 PVC）。
   - `tar --numeric-owner -cp | gzip -1 | send.py` → `recv.py | gzip -dc | tar -xp`；兩端各算串流 sha256，`manifest.py` 比對兩邊目錄清單指紋。
   - 接收端先把新服務初始化的內容改名成 `.fresh-<日期>`、重試時把沒收完的改名成 `.partial-<時間>`，**不刪**。
   - 走節點 IP、不走 pod 網路（TUF 的 pod 網路壞了，見下）。
5. 開新的（`--replicas=1`），驗收；`og_hosts.py` 唯讀查正式站 Omnigent 主機狀態。

## 這次查到的叢集狀況（會影響搬遷）
- **TUF 換了 IP**：現在走 WiFi `wlo1` 192.168.2.85，但 k3s／flannel 登記的還是 192.168.2.191 ⇒ 這就是 TUF 的 pod 網路壞掉（查不到 DNS）的原因；
  API 還管得到它，是因為 k3s agent 有自己連回 server 的通道。要修得在 TUF 上改 k3s 的 node-ip（或接回有線），會重啟 TUF 上的工作負載。
- **小主機登記的 InternalIP 也是舊的**：cluster3／6／7／8 的 InternalIP 與 flannel public-ip 不同；實際位址是 flannel 那個（例 cluster7＝.37，不是 .131）。
  所以 `kubectl top` 抓不到這幾台；節點對節點連線要用實際位址。cluster3 目前 unreachable。
- **TUF→cluster7 只有約 2.3 MB/s**（WiFi）。pi5 資料用 gzip -1 壓（約 2.4 倍）後有效約 6 MB/s。
- **筆電的 k3s 會因 swap 用光而自己重啟**（21:17，controller-manager 續不了 lease ⇒ exit 1 ⇒ systemd 重啟，約 40 秒）。大量傳輸別走筆電。
- **小資料改走 API，但要分段驗**：code-server 142MB 直接 `kubectl exec … tar | kubectl exec -i … tar` 會被截斷（tar: Unexpected EOF）。
  改成來源 pod 先打包成檔案＋sha256 → 抓回本機比 sha → 傳到目標 pod 比 sha → 解開，再用 `manifest.py --content` 比兩邊（`code-server-*-helper.yaml`）。
