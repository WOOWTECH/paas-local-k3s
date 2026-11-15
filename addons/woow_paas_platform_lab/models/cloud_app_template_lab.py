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
LAB_VISIBLE_SLUGS = ("postgresql", "redis", "n8n", "odoo", "litellm", "emqx")

# chart 預設值裡指向 JCR、但範本 helm_default_values 沒覆寫的映像（2026-11-15 實查 chart 0.2.26/0.2.27、litellm 0.3.16、emqx 0.1.11）。
# 只補 registry／repository，tag／digest 沿用 chart 預設（與 tools/images.txt 複製到 ghcr 的同一顆）。
CHART_DEFAULT_IMAGE_FIXES = {
    "woow-odoo": [(("postgres", "image"), {"registry": GHCR_REGISTRY, "repository": GHCR_REPO_DIR + "paas-postgres"})],
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
    new_values = _rewrite(json.loads(json.dumps(values)))
    if slug in LAB_VISIBLE_SLUGS:
        new_values = _apply_chart_default_fixes(new_chart, new_values)
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
