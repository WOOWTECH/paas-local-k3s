"""woowtech Cloud 存取控制：把 Woow Website Auth 的規則延伸到 /woow 平台與平台 API。

web auth 只在網站前台（website=True 的路由）攔截；/woow 與平台的 API 都是 website=False，原本管不到。
這裡在 _pre_dispatch（登入驗證之後）對「需要登入（auth='user'）的非網站路由」套用同一套規則：
- 候選路徑＝請求路徑＋路由別名（同 web auth）；平台模組的端點再加上 /woow，一條 /woow 規則就管住整個平台
- 只看 auth='user' 的路由：operator 回呼、webhook、API token 等機器路由（none／public／bearer）一律不碰
- 管理員（設定權限）永遠放行，避免把自己鎖在平台外
- 不通過時沿用 web auth 的拒絕行為（_deny_access：已登入→存取拒絕頁，其餘照規則設定）
"""
from odoo import models
from odoo.http import request

from odoo.addons.woow_website_auth.models.ir_http import _BYPASS_PREFIXES, candidate_paths

PLATFORM_PATH = "/woow"
PLATFORM_MODULES = ("odoo.addons.woow_paas_platform.", "odoo.addons.woow_paas_platform_lab.")


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _pre_dispatch(cls, rule, args):
        super()._pre_dispatch(rule, args)
        routing = getattr(rule.endpoint, "routing", None) or {}
        if routing.get("website") or routing.get("auth") != "user":
            return
        path = request.httprequest.path
        if path.startswith(_BYPASS_PREFIXES):
            return
        user = request.env.user
        if user._is_superuser() or user._is_system():
            return
        paths = list(candidate_paths(path, rule))
        module = getattr(rule.endpoint, "__module__", "") or ""
        if module.startswith(PLATFORM_MODULES) and PLATFORM_PATH not in paths:
            paths.append(PLATFORM_PATH)
        for auth_rule in cls._woow_find_rules(paths):
            if not cls._woow_rule_allows(auth_rule, user):
                cls._deny_access(auth_rule, path)
