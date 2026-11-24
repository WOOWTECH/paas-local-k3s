"""Lab overlay：把 6 個第一階段範本的 chart／image 座標從 JCR 改指 ghcr.io/woowtech。

不改上游程式，只在資料層後製：data/lab_overrides.xml 的 <function> 每次 install／-u 都呼叫
_lab_apply_registry_overrides()，所以上游 seed（noupdate=0）洗回來之後仍會再套一次。
"""
import base64
import json
import logging
import re

from odoo import api, models
from odoo.tools import file_open

_logger = logging.getLogger(__name__)

JCR_CHART_PREFIX = "oci://jcr-prod.woowtech.io/woow-paas-docker-local/"
GHCR_CHART_PREFIX = "oci://ghcr.io/woowtech/charts/"
JCR_IMAGE_PREFIX = "jcr-prod.woowtech.io/woow-paas-docker-local/"
GHCR_IMAGE_PREFIX = "ghcr.io/woowtech/"
JCR_REGISTRY = "jcr-prod.woowtech.io"
JCR_REPO_DIR = "woow-paas-docker-local/"
GHCR_REGISTRY = "ghcr.io"
GHCR_REPO_DIR = "woowtech/"

# 第一階段只開這 6 個（使用者 2026-11-15 決定）；其餘範本 is_hidden=True 等第二階段。
# postgresql／redis 在上游是 is_active=False（#562：Bitnami 2025-08 搬遷後預設映像只剩 :latest，上游不釘）；
# lab 依使用者決定開啟，映像沿用 chart 預設的 docker.io/bitnami/*:latest（浮動，已知風險）。
LAB_VISIBLE_SLUGS = ("postgresql", "redis", "n8n", "odoo", "litellm", "emqx",
                     # 第二批（使用者 2026-11-15 晚：「再去上架實作實測 Pi agent Hermes od omnigent」）
                     "pi-agent", "hermes-agent", "open-design", "omnigent",
                     # 第三批（使用者 2026-11-15 夜：「去搬剩下還沒搬過去的」）：正式站對外開放的其餘 13 個。
                     # 正式站也隱藏的 6 個（ha-paas、ha-full-apporo、mcp-k8s、mcp-odoo-manage、mcp-opendesign、mcp-vk）維持隱藏。
                     # haos、mcp-k8s 已移除（見下方 LAB_REMOVED_SLUGS）；mcp-vk 上游 11-14 已刪範本。
                     "code-server", "ha-full", "headscale", "nextcloud", "tailscale",
                     "mcp-emqx", "mcp-headscale", "mcp-hermes", "mcp-litellm", "mcp-n8n", "mcp-nextcloud", "mcp-odoo",
                     # 本機專用（2026-11-17，使用者：「cf web gui PaaS 版，工作區裡的服務都能透過它開外網」）
                     "cf-tunnel-webgui",
                     # 2026-11-18 使用者：「做一份專屬連結 apporo odoo paas 的 k3s 版本」→ 選「也上架到本機 lab PaaS」
                     "apporo-cf-tunnel-webgui",
                     # 2026-11-23 使用者：「把同樣 mausbot 上架到本地的 k3s paas」→ 平台升到正式站同版（18.0.2.0.31）後上架
                     "woowtechbot")

# 本機移除的範本：停用（is_active=False）＋隱藏，平台不列、API 也開不出來。範本是平台內建目錄的一筆（上游 seed
# noupdate=0），刪掉的話下次 -u woow_paas_platform 會長回來，所以用停用代替刪除。
# haos：使用者 2026-11-16「這個去移除，目前不需要」。之前跑不起來的原因：HAOS 映像是 32GiB 虛擬磁碟，CDI 匯入要求
# 節點剩餘空間 ≥ 32GiB，4GB 小節點的磁碟最多只剩 31GiB（2026-11-15 實測）。殘留的 DataVolume 已刪。
# 要加回：從這裡拿掉、把 "haos" 放回 LAB_VISIBLE_SLUGS、tools/images-rest.txt／mirror-charts.sh 補回，跑 tools/lab-overlay-update.sh。
# mcp-k8s：使用者 2026-11-24 決定 K8s MCP 封存下架、之後不再維護（woow-mcp-server #162、平台 #2541／#2542 已合併，
# 封存 tag archive/*k8s*-20261124）。上游 18.0.2.0.33 起 seed 沒有這個範本；本機平台還在 .31，先停用。本機 0 台服務引用它，
# 所以之後升 .33 時 -u 刪範本不會被 cloud_service.template_id 的 ondelete=restrict 擋住。
LAB_REMOVED_SLUGS = ("haos", "mcp-k8s")

# chart 位置例外：GHCR 上 charts/omnigent 已是別的專案的「公開」package，WOOW 的 omnigent chart 推進去會變公開
# → 改放私有的 paas-charts/omnigent（tools/mirror-charts.sh 同步）。
CHART_PATH_OVERRIDES = {
    "omnigent": "oci://ghcr.io/woowtech/paas-charts/omnigent",
}

# lab 叢集參數（只有這個叢集成立的值）：kube-router 在 DNAT 之後比對 egress，console／omnigent server 連 API
# 要放行 apiserver 真實位址（本機 = 筆電節點 192.168.2.10:6443），不能只有 ClusterIP。
LAB_APISERVER_CIDRS = "10.43.0.1/32,192.168.2.10/32"

# 方案規格（只改 cs_*，價格／名稱不動）：平台把方案 RAM 當 limits、一半當 requests（_apply_plan_spec_overlay）。
# pi-agent 方案 8GB → requests 4Gi，本機 4GB 節點（可配置約 3.7GiB）永遠排不上；omnigent 的 runner 會拿 8Gi limits。
# ⚠ 這些方案在上游是 noupdate=1：別的模組用 XML <record> 覆寫在 -u 時會被略過（2026-11-15 實測），
#   所以用 Python 寫；上游 -u 也不會洗回去。
# 使用者 2026-11-16：內部使用，關閉扣款流程（前台也藏掉點數／儲值／帳單，見 static/src/paas/lab_no_billing.*）。
# 做法是平台原生支援的「0 元一期」：方案一律 0 元、不試用 → 開通／換方案／續訂都不碰錢包、不開電子發票、不會欠款；
# 再停掉會扣款或會因「沒在扣款」而告警的排程。原本的價格與試用長度第一次套用時存進下面這個參數，要恢復收費照它還原。
LAB_PLAN_TERMS_SNAPSHOT_PARAM = "woow_paas_platform_lab.plan_terms_before_charging_off"
LAB_CHARGING_CRONS_OFF = (
    "woow_subscription.ir_cron_billing_run",                # 每日計費（模組預設就關；保持關）
    "woow_subscription.ir_cron_lifecycle_run",              # 合約到期（同上）
    "payment_ecpay_ecpg.ir_cron_ecpay_subscription_run",    # 綠界信用卡定期扣款
    "woow_paas_platform.ir_cron_low_balance_warning",       # 續訂前餘額不足提醒
    "woow_paas_platform.ir_cron_billing_silence_alert",     # 「計費靜默」告警（扣款關掉後會一直誤報）
)

# 使用者 2026-11-16：「名稱裡的月繳／訂閱拿掉，相關的都隱藏，因為是內部使用」。
# 方案名稱去掉計費字樣（原名第一次套用時存進下面的參數）；後台的會計／銷售／帳務選單與贈點動作藏起來（active=False／解除綁定，
# 要恢復就反過來設）。只動介面與名稱，模型與資料都還在。
LAB_PLAN_NAMES_SNAPSHOT_PARAM = "woow_paas_platform_lab.plan_names_before_internal"
LAB_HIDDEN_MENUS = (
    "account.menu_finance",                                  # 發票（含 訂閱／待開票／方案）
    "sale.sale_menu_root",                                   # 銷售（含 禮品卡及電子錢包）
    "woow_paas_platform.menu_billing_incidents",             # Woow PaaS › 帳務事件
    "woow_paas_platform.menu_ecpg_bind_auth_void",           # Woow PaaS › 綁卡驗證授權取消
    "woow_paas_platform.menu_llm_free_fallback",             # AI 模型 › 免費試用備援
    "woow_paas_platform.menu_llm_credit_orders_backoffice",  # AI 模型 › Credit Orders
    "woow_paas_platform.menu_llm_known_discrepancies",       # AI 模型 › 已知額度差額
    "woow_paas_platform.menu_llm_manual_credit",             # AI 模型 › Manual Credit
    "woow_paas_platform.menu_llm_manual_credit_reports",     # AI 模型 › Monthly Credit Reports
    # 使用者 2026-11-16「庫存移除」：stock 解除安裝會連平台一起移除（woow_paas_platform → ecpay_invoice_tw → stock），只能藏選單
    "stock.menu_stock_root",                                 # 庫存
)
LAB_UNBOUND_ACTIONS = (
    "woow_paas_platform.action_gift_grant_wizard",           # 聯絡人「動作」選單裡的 Grant Wallet Credits
)


def lab_internal_plan_name(name):
    """純函式：方案名稱拿掉計費字樣。「n8n雲端訂閱服務（6人）+5 存取席位 月繳」→「n8n雲端服務（6人）+5 存取席位」。"""
    new = (name or "").replace("雲端訂閱服務", "雲端服務").replace("訂閱服務", "服務").replace("訂閱", "")
    new = re.sub(r"\s*(?:月繳|年繳)", "", new)
    return re.sub(r"\s{2,}", " ", new).strip() or name


LAB_PLAN_SPECS = {
    "woow_paas_platform.plan_pi_agent_monthly": {"cs_ram_gb": 3.0},
    "woow_paas_platform.plan_pi_agent_yearly": {"cs_ram_gb": 3.0},
    "woow_paas_platform.plan_omnigent_monthly": {"cs_ram_gb": 3.0, "cs_vcpu": 2},
    "woow_paas_platform.plan_omnigent_yearly": {"cs_ram_gb": 3.0, "cs_vcpu": 2},
    # 第三批：code-server 8GB（requests 會是 4Gi）、nextcloud 4GB（requests 2Gi）→ 3GB
    "woow_paas_platform.plan_code_server_monthly": {"cs_ram_gb": 3.0},
    "woow_paas_platform.plan_code_server_yearly": {"cs_ram_gb": 3.0},
    "woow_paas_platform.plan_nextcloud_monthly": {"cs_ram_gb": 3.0},
    "woow_paas_platform.plan_nextcloud_yearly": {"cs_ram_gb": 3.0},
    # 2026-11-23 woowtechbot：正式站 4 vCPU／8 GB／20 GB；使用者選「TUF＋縮小 2/4/20」（requests 會是 0.5 CPU／2Gi）
    "woow_paas_platform.plan_woowtechbot_monthly": {"cs_vcpu": 2, "cs_ram_gb": 4.0, "cs_storage_gb": 20},
    "woow_paas_platform.plan_woowtechbot_yearly": {"cs_vcpu": 2, "cs_ram_gb": 4.0, "cs_storage_gb": 20},
}

# 市集卡片顯示的最低規格跟著本機方案（平台不拿它檢查方案，只在方案沒寫規格時當預設）。
LAB_TEMPLATE_MIN_SPECS = {
    "woowtechbot": {"min_vcpu": 2, "min_ram_gb": 4.0},
}

# chart 預設值裡指向 JCR、但範本 helm_default_values 沒覆寫的映像（2026-11-15 實查 chart 0.2.26/0.2.27、litellm 0.3.16、emqx 0.1.11）。
# 只補 registry／repository，tag／digest 沿用 chart 預設（與 tools/images.txt 複製到 ghcr 的同一顆）。
CHART_DEFAULT_IMAGE_FIXES = {
    "woow-odoo": [(("postgres", "image"), {"registry": GHCR_REGISTRY, "repository": GHCR_REPO_DIR + "paas-postgres"})],
    # nextcloud chart 0.1.9：postgresql.image.repository 是含 registry 的完整路徑（tag 17.11-20260928.1549，第一批已複製）
    "nextcloud": [(("postgresql", "image"), {"repository": GHCR_IMAGE_PREFIX + "paas-postgres"})],
}


def _rewrite(obj):
    """遞迴改寫 helm values：repository 全路徑、以及 registry+repository 拆開的兩種寫法。"""
    if isinstance(obj, dict):
        if obj.get("registry") == JCR_REGISTRY and isinstance(obj.get("repository"), str) \
                and obj["repository"].startswith(JCR_REPO_DIR):
            obj["registry"] = GHCR_REGISTRY
            obj["repository"] = GHCR_REPO_DIR + obj["repository"][len(JCR_REPO_DIR):]
        for k, v in list(obj.items()):
            if isinstance(v, str) and v.startswith(JCR_IMAGE_PREFIX):
                obj[k] = GHCR_IMAGE_PREFIX + v[len(JCR_IMAGE_PREFIX):]
            else:
                _rewrite(v)
    elif isinstance(obj, list):
        for v in obj:
            _rewrite(v)
    return obj


# 範本層的值修正（只在 lab）：Bitnami chart 預設會建自己的 NetworkPolicy，egress 規則是 `- {}`（全放行），
# 被 operator 的 ValidatingAdmissionPolicy paas-operator-tenant-netpol-guard（woow_paas_platform #1436）拒絕
# → helm install 失敗（2026-11-15 實測）。上游這兩個範本 is_active=False，所以正式站沒遇過。
# 關掉 chart 自帶的 NetworkPolicy；租戶 namespace 本來就有 operator 建的 5 條 baseline NetworkPolicy。
TEMPLATE_VALUE_FIXES = {
    "postgresql": {"primary": {"networkPolicy": {"enabled": False}},
                   "readReplicas": {"networkPolicy": {"enabled": False}}},
    "redis": {"networkPolicy": {"enabled": False}},
    # 本機可用節點都是 4GB（可配置約 3.7GiB）：範本原值 requests 2Gi／limits 8Gi 排得上但會把整台吃爆，
    # 壓到 requests 1Gi／limits 3Gi（這兩個範本的方案沒有 cs_* 規格，平台不會再覆寫）。
    "open-design": {"resources": {"requests": {"cpu": "500m", "memory": "1Gi"},
                                  "limits": {"cpu": "2", "memory": "3Gi"}}},
    "hermes-agent": {"agent": {"resources": {"requests": {"cpu": "250m", "memory": "1Gi"},
                                             "limits": {"cpu": "2", "memory": "3Gi"}}}},
}

# 範本版本釘選（本機比正式站新）：chart 版本＋主映像 tag@digest。正式站範本升到同版後就拿掉。
# 2026-11-16 code-server：本機 k3s 的 code-server-codex 搬進 PaaS 要用到 Codex CLI，只有 11/10 映像才有；
# chart 0.1.12 已合併進 woow-paas-charts main（Pi、Claude、Codex 共用 skills／MCP），正式站範本仍是 0.1.9／20261018.0107。
# 映像與 chart 已複製到 GHCR（tools/images-code-server.txt、tools/mirror-charts.sh "code-server 0.1.12"）。
# 2026-11-23 平台 18.0.2.0.14 → 18.0.2.0.31：上游 seed 換了 odoo／omnigent／9 個 mcp-* 的 chart 或映像，新版沒有複製到 GHCR，
# 先釘回本機已複製的版本（值取自升級前的本機範本）；要跟上正式站時把映像／chart 複製過來再拿掉。woowtechbot 釘最新修正版
# （正式站範本仍是 chart 0.1.2／20261121.0756，服務 461 已跑 0.1.3／20261123.0428）。
#   image_tag：寫進 values.image.tag；values：其他要釘的值（deep-set）。
# 2026-11-24 使用者：「讓這些更新優化過的 mcp server 可以在本地的 k3s paas 上面部署啟用」→ MCP 改釘 P3
# （woow-mcp-server main 4e8da3f0，正式站服務 11-23 已換到這版）：值照正式站 R2 18.0.2.0.33 seed
# （feat/woow-subscription-engine 7304aafd），chart 仍是 mcp-server 0.1.10、其他 values 與 .31 seed 相同（只差 image.tag）。
# 在售 7 個的映像已複製到 GHCR（tools/images-mcp-p3.txt）；mcp-opendesign 正式站也隱藏，照 seed 釘但沒複製映像。
# mcp-k8s 11-24 封存下架（見 LAB_REMOVED_SLUGS），不再釘。本機平台升到 .33 以後這 8 筆與 seed 相同，可以整段拿掉。
_MCP_LAB_TAGS = {
    "mcp-emqx": "4e8da3f06861816fae8bf35773dea591fad54db8@sha256:67cf042906d4741b2114172e2ecf9b149768da0d8f7f2e81850f3242ef09c74e",
    "mcp-headscale": "4e8da3f06861816fae8bf35773dea591fad54db8@sha256:f0274fee1430bd8f3856422afd7c50930caeeb8bf400f771c4205ae2ecb36690",
    "mcp-hermes": "4e8da3f06861816fae8bf35773dea591fad54db8@sha256:0044fde1f1e2be87daa7f5d9dbc6e298addb8f93ec8f7fd41b74ab610f14e678",
    "mcp-litellm": "4e8da3f06861816fae8bf35773dea591fad54db8@sha256:6052fcb2501e67bb0362e2aa50615928b3f074040c67d9500bc46bc24099f9f1",
    "mcp-n8n": "4e8da3f06861816fae8bf35773dea591fad54db8@sha256:5c78273f8f1551c183285f744b102e07a9bc4c34dee83a82096dd640db071076",
    "mcp-nextcloud": "4e8da3f06861816fae8bf35773dea591fad54db8@sha256:7adf3ce4d15f91724d0c81f436d720ee3791a88644d592bfd7f844cbd5e4b11e",
    "mcp-odoo": "4e8da3f06861816fae8bf35773dea591fad54db8@sha256:511242c5be5b2e788d728a1a5bb5ea7a012a96758f40b39de010141f8aedd748",
    "mcp-opendesign": "4e8da3f06861816fae8bf35773dea591fad54db8@sha256:b23e2f1532f95189271eeecf39288ac997fe0f7615cb8181c4ef86ab0b8dc711",
}
TEMPLATE_VERSION_PINS = {
    "code-server": {"chart_version": "0.1.12",
                    "image_tag": "20261110.1622@sha256:0271957892a382d88c141c4a0d3a2b3b53da6cd0b56ba7239fe229608d6dcb5b"},
    "odoo": {"chart_version": "0.2.26",
             "values": {"image": {"tag": "20261108.0727",
                                  "digest": "sha256:a49bfc8cc912314826a60e62d7c12b672cc19726433c6b6ac3998ef969863e1b"}}},
    "omnigent": {"chart_version": "0.1.19",
                 "image_tag": "20261111.0647@sha256:c6b6cab6478f06f6a36e3731cbd619d8d1bea8ece201da6e97c9dea97c38d72e",
                 "values": {"runner": {"image": "ghcr.io/woowtech/omnigent-host:20261111.0647@sha256:701101d009847e7dfb2c607314d42a38d171c9c44732c0e2a624177e02ce23bb"}}},
    "woowtechbot": {"chart_version": "0.1.3",
                    "image_tag": "20261123.0428@sha256:4540b2bc890c828492ee7e976a3876476a7159f736131865255787c82c287433"},
    **{slug: {"chart_version": "0.1.10", "image_tag": tag} for slug, tag in _MCP_LAB_TAGS.items()},
}


def _deep_set(dst, fix):
    for k, v in fix.items():
        if isinstance(v, dict):
            node = dst.get(k)
            if not isinstance(node, dict):
                node = {}
                dst[k] = node
            _deep_set(node, v)
        else:
            dst[k] = v
    return dst


def _chart_basename(chart_name):
    return (chart_name or "").rstrip("/").rsplit("/", 1)[-1]


def _apply_chart_default_fixes(chart_name, values):
    """把 chart 預設指向 JCR 的映像補成 ghcr（只在範本沒有自己指定 registry／repository 時）。"""
    for path, fix in CHART_DEFAULT_IMAGE_FIXES.get(_chart_basename(chart_name), []):
        node = values
        for key in path:
            nxt = node.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                node[key] = nxt
            node = nxt
        for k, v in fix.items():
            cur = node.get(k)
            if cur is None or (isinstance(cur, str) and (cur == JCR_REGISTRY or cur.startswith(JCR_REPO_DIR) or cur.startswith(JCR_IMAGE_PREFIX))):
                node[k] = v
    return values


def lab_transform(slug, chart_name, values):
    """純函式（可在 Odoo 外測）：回傳 (new_chart_name, new_values)。"""
    new_chart = chart_name
    if (chart_name or "").startswith(JCR_CHART_PREFIX):
        new_chart = GHCR_CHART_PREFIX + chart_name[len(JCR_CHART_PREFIX):]
    if slug in CHART_PATH_OVERRIDES and (new_chart or "").startswith(GHCR_CHART_PREFIX):
        new_chart = CHART_PATH_OVERRIDES[slug]
    new_values = _rewrite(json.loads(json.dumps(values)))
    if slug in LAB_VISIBLE_SLUGS:
        new_values = _apply_chart_default_fixes(new_chart, new_values)
        if slug in TEMPLATE_VALUE_FIXES:
            new_values = _deep_set(new_values, json.loads(json.dumps(TEMPLATE_VALUE_FIXES[slug])))
    pin = TEMPLATE_VERSION_PINS.get(slug)
    if pin:
        if "image_tag" in pin:
            new_values = _deep_set(new_values, {"image": {"tag": pin["image_tag"]}})
        if "values" in pin:
            new_values = _deep_set(new_values, json.loads(json.dumps(pin["values"])))
    return new_chart, new_values


# 本機專用的兩個範本（2026-11-17，使用者選「先補推播功能再整組搬」）：把手架的 Odoo App 推播測試環境
# （demo111／demo222／apporo-push-test＋woow-fcm-central）改由 PaaS 部署與管理。正式站沒有這兩個範本。
# chart 原始碼在控制 repo charts/，推在 oci://ghcr.io/woowtech/charts（私有）。不在 LAB_VISIBLE_SLUGS，
# 所以 _lab_apply_registry_overrides 會把它們藏起來：只由管理員用 tools/migrate/ 的腳本開服務。
# 方案沒有 cs_* 規格 ⇒ 平台不覆寫資源，資源由服務自己的 helm_values 決定。
LAB_PUSH_TEMPLATES = (
    {"slug": "odoo-push-test", "name": "Odoo App 推播測試環境", "chart": "odoo-push-test", "version": "0.1.0",
     "port": 8080, "ingress": True, "category": "web", "plan": "Odoo App 推播測試環境（內部）",
     "description": "官方 Odoo 18 映像＋FCM 推播 sidecar（woow 走叢集內推播中心、apporo 走 Apporo 的 Cloud Run），"
                    "給 Odoo App 測試用；可選擇沿用既有 Cloudflare tunnel 的網址。"},
    {"slug": "fcm-central", "name": "FCM 推播中心", "chart": "fcm-central", "version": "0.1.0",
     "port": 8000, "ingress": False, "category": "devops", "plan": "FCM 推播中心（內部）",
     "description": "woow 品牌的 FCM 推播中心（whitelist-service＋token-vending-service＋postgres），"
                    "只在叢集內提供服務、沒有公開網址；Google 推播金鑰與 TokenReview 權限要另外建。"},
    # 2026-11-17 使用者：「設計建立 cf web gui PaaS 版本，功能要跟 HA addon／Podman 版一模一樣，部署在本地 k3s PaaS，
    # 在工作區中開啟部署，同工作區的服務都能透過它開外網（例如五套 pi agent 一次開通）」→ 開通走平台 Security Access。
    # 程式與 chart：GitHub WOOWTECH/Woow_k3s_cf_tunnel_webgui（公開）；chart 推 oci://ghcr.io/woowtech/charts（私有）。
    # 在 LAB_VISIBLE_SLUGS ⇒ 市集看得到。登入＝平台管理員密碼（has_admin_gui＋helm_secret，同 pi-agent）。
    {"slug": "cf-tunnel-webgui", "name": "Cloudflare Tunnel WebGUI", "chart": "cf-tunnel-webgui", "version": "0.1.1",
     "port": 8080, "ingress": True, "category": "devops", "plan": "Cloudflare Tunnel WebGUI（內部）",
     "admin_gui": True,
     "short": "把同工作區的服務開到外網：PaaS 連結（Security Access）、Token、或你自己的 Cloudflare",
     "tags": ["cloudflare", "tunnel", "security-access", "webgui"],
     "docs": "https://github.com/WOOWTECH/Woow_k3s_cf_tunnel_webgui#readme",
     "icon": "static/description/cf-tunnel-webgui.png",
     # PaaS 連結用 chart 預設（WOOW 正式站 aiot.woowtech.io、client woow-ha-smart-home、不寫路由），同 Podman／HA 版。
     # 11-18 前 lab 指向本機平台＋一鍵 API，使用者要求移除後改回預設。
     "values": {
         # 映像由 GitHub Actions 建（release.yml，tag v1.3.1，amd64＋arm64，GHCR 公開 package）
         "image": {"repository": "ghcr.io/woowtech/cf-tunnel-webgui",
                   "tag": "1.3.1@sha256:5abd92d634bfa062c26126564c43fb63dd1fbd6fdc0cb6f9ccb0603729ef4a1c"},
     },
     "description": "Cloudflare Tunnel 網頁管理介面（PaaS 版），與 Podman 版、Home Assistant 外掛版同樣的五個頁面與三種連結方式。\n"
                    "• PaaS 連結：用 WOOW PaaS（aiot.woowtech.io）帳號登入，連結 Security Access；網址在 PaaS 入口網站設定，"
                    "WebGUI 會列出這個工作區每個服務的內部位址。\n"
                    "• Token 連結：貼上 Cloudflare tunnel token。\n"
                    "• 客製連結：登入你自己的 Cloudflare 帳號，勾選工作區裡的服務，一次建好 tunnel、DNS 與規則。\n"
                    "登入帳號 admin，密碼是這個服務的管理員密碼。開出去的網址是公開的，請確認服務本身有登入保護。"},
    # 2026-11-18 Apporo 版（WOOWTECH/Apporo_k3s_cf_tunnel_webgui）：英文介面＋Apporo 品牌，PaaS 連結接 www.apporo.ai 的
    # Security Access（chart 預設：client woow-ha-smart-home、不寫路由、網域 apporo.ai）。Apporo 平台沒有 k3s 服務，
    # 所以上架在 woowtech Cloud（lab）給內部用；正式交付給客戶時用獨立 Helm chart 裝到他們的 k3s。
    {"slug": "apporo-cf-tunnel-webgui", "name": "Apporo CF Tunnel Web", "chart": "apporo-cf-tunnel-webgui",
     "version": "1.0.0", "port": 8080, "ingress": True, "category": "devops", "plan": "Apporo CF Tunnel Web（內部）",
     "admin_gui": True,
     "short": "Apporo 版：把同工作區的服務開到外網（Apporo Security Access／Token／自己的 Cloudflare），英文介面",
     "tags": ["apporo", "cloudflare", "tunnel", "security-access"],
     "docs": "https://github.com/WOOWTECH/Apporo_k3s_cf_tunnel_webgui#readme",
     "icon": "static/description/apporo-cf-tunnel-webgui.png",
     "values": {
         # 映像由 GitHub Actions 建（WOOWTECH/Apporo_k3s_cf_tunnel_webgui release.yml，tag v1.0.0，amd64＋arm64，公開）
         "image": {"repository": "ghcr.io/woowtech/apporo-cf-tunnel-webgui",
                   "tag": "1.0.0@sha256:4a98105908c8347fd6a1caf5848001ce0a7cc2809d450db6e19d892309e1e08a"},
     },
     "description": "Apporo CF Tunnel Web（Kubernetes 版），與 Apporo 的 Podman 版、Home Assistant 外掛版同樣的五個頁面與三種連結方式，英文介面。\n"
                    "• Apporo Link：用 Apporo（www.apporo.ai）帳號登入，連結 Security Access；網址（名稱.apporo.ai）在 Apporo 入口網站設定，"
                    "WebGUI 會列出這個工作區每個服務的內部位址。\n"
                    "• Token：貼上 Cloudflare tunnel token。\n"
                    "• Setup（客製連結）：登入你自己的 Cloudflare 帳號，勾選工作區裡的服務，一次建好 tunnel、DNS 與規則。\n"
                    "登入帳號 admin，密碼是這個服務的管理員密碼。開出去的網址是公開的，請確認服務本身有登入保護。"},
)

# 11-18 使用者要求移除 lab 上為 WebGUI 加的「一鍵開通」API 與它的 OAuth client（連同 SA 恢復隱藏）。
# 每次 -u 都確認這個 client 不在（它的 token／code／device code 都是 ondelete=cascade）。
REMOVED_OAUTH_CLIENT_IDS = ("woow-cf-tunnel-webgui",)


class CloudAppTemplateLab(models.Model):
    _inherit = "woow_paas_platform.cloud_app_template"

    @api.model
    def _lab_apply_registry_overrides(self):
        templates = self.sudo().search([])
        changed = 0
        for t in templates:
            vals = {}
            try:
                values = json.loads(t.helm_default_values or "{}")
            except (TypeError, ValueError):
                values = None
            if isinstance(values, dict):
                new_chart, new_values = lab_transform(t.slug, t.helm_chart_name, values)
                if new_values != values:
                    vals["helm_default_values"] = json.dumps(new_values, ensure_ascii=False, indent=2)
            else:
                new_chart, _ = lab_transform(t.slug, t.helm_chart_name, {})
            if new_chart != t.helm_chart_name:
                vals["helm_chart_name"] = new_chart
            pin = TEMPLATE_VERSION_PINS.get(t.slug)
            if pin and t.helm_chart_version != pin["chart_version"]:
                vals["helm_chart_version"] = pin["chart_version"]
            # 第一階段曝光層：6 個以外一律隱藏（只動 is_hidden，不動 conceal_instances）；6 個一律 is_active
            want_hidden = t.slug not in LAB_VISIBLE_SLUGS
            if t.is_hidden != want_hidden and not t.conceal_instances:
                vals["is_hidden"] = want_hidden
            if t.slug in LAB_VISIBLE_SLUGS and not t.is_active:
                vals["is_active"] = True
            if t.slug in LAB_REMOVED_SLUGS and t.is_active:
                vals["is_active"] = False
            for field, want in LAB_TEMPLATE_MIN_SPECS.get(t.slug, {}).items():
                if t[field] != want:
                    vals[field] = want
            if vals:
                t.write(vals)
                changed += 1
        _logger.info("woow_paas_platform_lab: registry/visibility overrides applied to %s template(s)", changed)
        return True

    @api.model
    def _lab_setup_billing(self):
        """fresh install 沒有人去「設定 → 發票 → 訂閱計費」選日記帳 → 開通服務被拒
        （Subscription journal is not configured）。正式站是人工設的；lab 每次 -u 補上（已設就不動）。"""
        Journal = self.env["account.journal"].sudo()
        for company in self.env["res.company"].sudo().search([]):
            vals = {}
            if not company.woow_subscription_journal_id:
                j = Journal.search([("company_id", "=", company.id), ("type", "=", "sale")], order="id", limit=1)
                if j:
                    vals["woow_subscription_journal_id"] = j.id
            if not company.woow_subscription_settlement_journal_id:
                j = Journal.search([("company_id", "=", company.id), ("type", "in", ("bank", "cash"))], order="id", limit=1)
                if j:
                    vals["woow_subscription_settlement_journal_id"] = j.id
            if vals:
                company.write(vals)
            _logger.info("woow_paas_platform_lab: billing journals for company %s: %s", company.id, vals or "already set")
        return True

    @api.model
    def _lab_setup_cluster_params(self):
        """lab 叢集專屬的 ir.config_parameter（正式站由 ops 各自設定，不進上游 seed）。"""
        icp = self.env["ir.config_parameter"].sudo()
        # Woow MCP（woow-mcp-gateway）要租戶建 API token；總開關預設關（寫入權限的開關不動，維持關閉）
        if (icp.get_param("woow_paas_platform.api_token_enabled") or "").strip().lower() not in ("1", "true", "yes", "on"):
            icp.set_param("woow_paas_platform.api_token_enabled", "True")
            _logger.info("woow_paas_platform_lab: api_token_enabled set to True")
        if icp.get_param("woow_paas_platform.apiserver_cidrs") != LAB_APISERVER_CIDRS:
            icp.set_param("woow_paas_platform.apiserver_cidrs", LAB_APISERVER_CIDRS)
            _logger.info("woow_paas_platform_lab: apiserver_cidrs set to %s", LAB_APISERVER_CIDRS)
        return True

    @api.model
    def _lab_setup_plans(self):
        changed = []
        for xmlid, vals in LAB_PLAN_SPECS.items():
            plan = self.env.ref(xmlid, raise_if_not_found=False)
            if not plan:
                continue
            diff = {k: v for k, v in vals.items() if plan[k] != v}
            if diff:
                plan.sudo().write(diff)
                changed.append(xmlid.split(".")[-1])
        _logger.info("woow_paas_platform_lab: plan specs adjusted: %s", changed or "already set")
        return True


    @api.model
    def _lab_ensure_push_templates(self):
        """建立（或對齊 chart 版本）LAB_PUSH_TEMPLATES 的範本與各自一個 0 元內部方案。冪等。"""
        Plan = self.env["woow.subscription.plan"].sudo()
        done = []
        for spec in LAB_PUSH_TEMPLATES:
            vals = {
                "name": spec["name"],
                "slug": spec["slug"],
                "helm_repo_url": "",
                "helm_chart_name": GHCR_CHART_PREFIX + spec["chart"],
                "helm_chart_version": spec["version"],
                "workload_type": "container",
                "admin_password_carrier": "config_json",
                "app_admin_reset_kind": "none",
                "credential_change_restart_scope": "service",
                "category": spec["category"],
                "default_port": spec["port"],
                "ingress_enabled": spec["ingress"],
                "has_admin_gui": bool(spec.get("admin_gui")),
                "full_description": spec["description"],
            }
            if spec.get("admin_gui"):
                # 同 pi-agent：nginx basic auth，密碼走 config.sensitive.admin_password（平台可重設）
                vals["admin_password_carrier"] = "helm_secret"
            if spec.get("short"):
                vals["description"] = spec["short"]
            if spec.get("tags"):
                vals["tags"] = json.dumps(spec["tags"])
            if spec.get("docs"):
                vals["documentation_url"] = spec["docs"]
            if spec.get("icon"):
                with file_open(f"woow_paas_platform_lab/{spec['icon']}", "rb") as handle:
                    vals["icon"] = base64.b64encode(handle.read())
            tmpl = self.sudo().with_context(active_test=False).search([("slug", "=", spec["slug"])], limit=1)
            if not tmpl:
                tmpl = self.sudo().create(dict(vals, helm_default_values=json.dumps(spec.get("values") or {}),
                                               is_active=True, is_hidden=True))
                done.append(f"{spec['slug']} created")
            else:
                diff = {k: v for k, v in vals.items() if tmpl[k] != v}
                if "values" in spec:
                    try:
                        current = json.loads(tmpl.helm_default_values or "{}")
                    except ValueError:
                        current = None
                    if current != spec["values"]:
                        diff["helm_default_values"] = json.dumps(spec["values"])
                if diff:
                    tmpl.write(diff)
                    done.append(f"{spec['slug']} updated {sorted(diff)}")
            if not tmpl.subscription_plan_ids:
                plan = Plan.create({
                    "name": spec["plan"],
                    "company_id": self.env.company.id,
                    "service_type": "cloud_service",
                    "interval_count": 1,
                    "interval_unit": "month",
                    "trial_unit": "day",
                    "is_open_ended": True,
                })
                tmpl.write({"subscription_plan_ids": [(4, plan.id)]})
                done.append(f"{spec['slug']} plan {plan.id}")
            # 開服務時平台要找方案對應的訂閱商品（product.template.woow_subscription_plan_id），沒有就拒絕
            Product = self.env["product.template"].sudo().with_context(active_test=False)
            for plan in tmpl.subscription_plan_ids:
                if not Product.search_count([("woow_subscription_plan_id", "=", plan.id)]):
                    Product.create({
                        "name": f"{plan.name} Subscription",
                        "type": "service",
                        "sale_ok": True,
                        "invoice_policy": "order",
                        "list_price": 0.0,
                        "woow_is_subscription": True,
                        "woow_subscription_plan_id": plan.id,
                    })
                    done.append(f"{spec['slug']} product for plan {plan.id}")
        _logger.info("woow_paas_platform_lab: push-test templates: %s", done or "already set")
        return True

    @api.model
    def _lab_remove_cf_webgui_oauth_client(self):
        """移除 WebGUI 專用的 OAuth client（冪等；不存在就什麼都不做）。"""
        Client = self.env["woow_paas_platform.oauth_client"].sudo().with_context(active_test=False)
        clients = Client.search([("client_id", "in", list(REMOVED_OAUTH_CLIENT_IDS))])
        if clients:
            clients.unlink()
        _logger.info("woow_paas_platform_lab: removed OAuth clients: %s", clients.ids or "none present")
        return True

    @api.model
    def _lab_disable_charging(self):
        """方案 0 元＋不試用＋停用扣款相關排程（每次 -u 都再套一次；已是 0 元／已停用就不動）。"""
        Plan = self.env["woow.subscription.plan"].sudo().with_context(active_test=False)
        icp = self.env["ir.config_parameter"].sudo()
        plans = Plan.search([])
        if not icp.get_param(LAB_PLAN_TERMS_SNAPSHOT_PARAM):
            icp.set_param(LAB_PLAN_TERMS_SNAPSHOT_PARAM, json.dumps(
                {str(p.id): [p.price, p.trial_length, p.trial_unit] for p in plans}, ensure_ascii=False))
            _logger.info("woow_paas_platform_lab: plan terms snapshot saved (%s plans)", len(plans))
        to_zero = plans.filtered(lambda p: p.price or p.trial_length)
        if to_zero:
            to_zero.write({"price": 0.0, "trial_length": 0})
        crons_off = []
        for xmlid in LAB_CHARGING_CRONS_OFF:
            cron = self.env.ref(xmlid, raise_if_not_found=False)
            if cron and cron.active:
                cron.sudo().write({"active": False})
                crons_off.append(xmlid.split(".")[-1])
        _logger.info("woow_paas_platform_lab: charging off — plans zeroed: %s, crons disabled: %s",
                     len(to_zero), crons_off or "already off")
        return True


    @api.model
    def _lab_internal_plan_names(self):
        """方案名稱去掉「訂閱／月繳／年繳」（每次 -u 再套一次；已是新名稱就不動）。"""
        Plan = self.env["woow.subscription.plan"].sudo().with_context(active_test=False)
        icp = self.env["ir.config_parameter"].sudo()
        plans = Plan.search([])
        if not icp.get_param(LAB_PLAN_NAMES_SNAPSHOT_PARAM):
            icp.set_param(LAB_PLAN_NAMES_SNAPSHOT_PARAM,
                          json.dumps({str(p.id): p.name for p in plans}, ensure_ascii=False))
        renamed = 0
        for plan in plans:
            new = lab_internal_plan_name(plan.name)
            if new != plan.name:
                plan.write({"name": new})
                renamed += 1
        _logger.info("woow_paas_platform_lab: plan names cleaned: %s", renamed)
        return True

    @api.model
    def _lab_hide_billing_backoffice(self):
        """後台：藏會計／銷售／帳務相關選單，解除「Grant Wallet Credits」在聯絡人上的綁定。"""
        hidden = []
        for xmlid in LAB_HIDDEN_MENUS:
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if menu and menu.active:
                menu.sudo().write({"active": False})
                hidden.append(xmlid)
        unbound = []
        for xmlid in LAB_UNBOUND_ACTIONS:
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if action and action.binding_model_id:
                action.sudo().write({"binding_model_id": False})
                unbound.append(xmlid)
        _logger.info("woow_paas_platform_lab: billing back office hidden — menus: %s, actions unbound: %s",
                     hidden or "already hidden", unbound or "already unbound")
        return True
