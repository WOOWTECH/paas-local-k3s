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
LAB_VISIBLE_SLUGS = ("postgresql", "redis", "n8n", "odoo", "litellm", "emqx")


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


class CloudAppTemplateLab(models.Model):
    _inherit = "woow_paas_platform.cloud_app_template"

    @api.model
    def _lab_apply_registry_overrides(self):
        templates = self.sudo().search([])
        changed = 0
        for t in templates:
            vals = {}
            if (t.helm_chart_name or "").startswith(JCR_CHART_PREFIX):
                vals["helm_chart_name"] = GHCR_CHART_PREFIX + t.helm_chart_name[len(JCR_CHART_PREFIX):]
            try:
                values = json.loads(t.helm_default_values or "{}")
            except (TypeError, ValueError):
                values = None
            if isinstance(values, dict):
                new_values = _rewrite(json.loads(json.dumps(values)))
                if new_values != values:
                    vals["helm_default_values"] = json.dumps(new_values, ensure_ascii=False, indent=2)
            # 第一階段曝光層：6 個以外一律隱藏（只動 is_hidden，不動 conceal_instances）
            want_hidden = t.slug not in LAB_VISIBLE_SLUGS
            if t.is_hidden != want_hidden and not t.conceal_instances:
                vals["is_hidden"] = want_hidden
            if vals:
                t.write(vals)
                changed += 1
        _logger.info("woow_paas_platform_lab: registry/visibility overrides applied to %s template(s)", changed)
        return True
