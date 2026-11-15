"""Lab overlay：把 6 個第一階段範本的 chart／image 座標從 JCR 改指 ghcr.io/woowtech。

不改上游程式，只在資料層後製：data/lab_overrides.xml 的 <function> 每次 install／-u 都呼叫
_lab_apply_registry_overrides()，所以上游 seed（noupdate=0）洗回來之後仍會再套一次。
"""
import json
import logging

from odoo import api, models

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
                     "code-server", "ha-full", "haos", "headscale", "nextcloud", "tailscale",
                     "mcp-emqx", "mcp-headscale", "mcp-hermes", "mcp-litellm", "mcp-n8n", "mcp-nextcloud", "mcp-odoo")

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
    # HAOS VM 範本是 2 核 4Gi：4GB 節點放不下（virt-launcher 還有額外開銷），壓到 HAOS 最低建議的 2Gi
    "haos": {"vm": {"memory": "2Gi"}},
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
    return new_chart, new_values


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
            # 第一階段曝光層：6 個以外一律隱藏（只動 is_hidden，不動 conceal_instances）；6 個一律 is_active
            want_hidden = t.slug not in LAB_VISIBLE_SLUGS
            if t.is_hidden != want_hidden and not t.conceal_instances:
                vals["is_hidden"] = want_hidden
            if t.slug in LAB_VISIBLE_SLUGS and not t.is_active:
                vals["is_active"] = True
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
