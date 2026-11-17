"""Lab overlay：給 Cloudflare Tunnel WebGUI（PaaS 版）用的 OAuth API。

使用者 2026-11-17：在工作區開一套 Cloudflare Tunnel WebGUI，就能把同工作區的服務（例如五套 pi agent）
透過 Security Access 一次開到外網，開通走平台、同仁不用有 Cloudflare 帳號。

上游的 HA／WebGUI OAuth API（controllers/ha_api.py）只有讀與 claim；新增／刪除路由只有入口網站的
session JSON-RPC。這裡補上 WebGUI 需要的五支（契約見 WOOWTECH/Woow_k3s_cf_tunnel_webgui docs/paas-api.md）：

  GET    /api/security-access/workspaces/lookup?namespace=   workspace:read          成員
  GET    /api/security-access/workspaces/<ws>/services       workspace:read          成員
  GET    /api/security-access/routes/check?prefix=           security-access:read
  POST   /api/security-access/accesses/<sa>/routes           security-access:routes  owner／admin
  DELETE /api/security-access/accesses/<sa>/routes/<route>   security-access:routes  owner／admin

閘門全部沿用上游同一把尺：`_authenticate`（scope）、`_check_workspace_access`（成員）、`_require_manage_role`
（owner／admin）、`sa._check_operation_allowed('write')`（訂閱／停權），名稱檢查用入口網站的
`_check_route_prefix`（格式＋平台 DB＋Cloudflare DNS），建立走 route model 自己的 create（同一個
savepoint 內 sync 到 operator）。只開公開路由（is_protected=False）：lab 沒有設定登入方式（IdP）。
"""
import json
import logging
import re
from urllib.parse import urlparse

from odoo.exceptions import ValidationError
from odoo.http import Controller, Response, request, route

from odoo.addons.woow_paas_platform.controllers import ha_api, oauth2
from odoo.addons.woow_paas_platform.controllers.security_access import SecurityAccessController
from odoo.addons.woow_paas_platform.services.workspace_quota import workspace_namespace

_logger = logging.getLogger(__name__)

ROUTES_SCOPE = "security-access:routes"
# device 同意頁顯示人話（上游的 dict 是 module 級，overlay 載入時補一筆）
oauth2.SCOPE_DESCRIPTIONS.setdefault(ROUTES_SCOPE, "為你的安全存取服務新增或移除公開網址")

MAX_ROUTES_PER_CALL = 10
SERVICE_SCHEMES = ("http", "https", "tcp", "ssh", "rdp")
WS_HASH_RE = re.compile(r"^[0-9a-f]{8}$")


def _json(data, status=200):
    return ha_api._json_response(data, status=status)


def _error(error, detail, status, **extra):
    return _json({"error": error, "detail": detail, **extra}, status=status)


def _auth(scope):
    return ha_api._authenticate(required_scopes=[scope])


class CfWebguiApi(Controller):

    # ---------------------------------------------------------------- workspace

    @route("/api/security-access/workspaces/lookup", type="http", auth="none", methods=["GET"], csrf=False)
    def cf_webgui_workspace_lookup(self, namespace=None, **kwargs):
        """namespace → 呼叫者是成員的那個 active workspace（WebGUI 自動選本工作區用）。"""
        result = _auth("workspace:read")
        if isinstance(result, Response):
            return result
        user, _token = result
        ns = (namespace or "").strip()
        prefix = request.env["ir.config_parameter"].sudo().get_param(
            "woow_paas_platform.namespace_prefix", "paas-ws-") or "paas-ws-"
        ws_hash = ns[len(prefix):] if ns.startswith(prefix) else ""
        not_found = _error("not_found", "No workspace of yours uses this namespace", 404)
        if not WS_HASH_RE.match(ws_hash):
            return not_found
        found = request.env["woow_paas_platform.workspace"].sudo().search([("ws_hash", "=", ws_hash)], limit=1)
        if not found or not ha_api._check_workspace_access(user, found.id):
            return not_found
        return _json({"workspace": {"id": found.id, "name": found.name, "slug": found.slug or "",
                                    "namespace": ns}})

    @route("/api/security-access/workspaces/<int:workspace_id>/services",
           type="http", auth="none", methods=["GET"], csrf=False)
    def cf_webgui_workspace_services(self, workspace_id, **kwargs):
        """工作區的雲端服務：名稱、範本、helm release（WebGUI 用 release 對上 K8s 的 Service）。"""
        result = _auth("workspace:read")
        if isinstance(result, Response):
            return result
        user, _token = result
        workspace = ha_api._check_workspace_access(user, workspace_id)
        if not workspace:
            return _error("Forbidden", "No access to this workspace", 403)
        ws = request.env["woow_paas_platform.workspace"].sudo().browse(workspace.id)
        domain = request.env["ir.config_parameter"].sudo().get_param("woow_paas_platform.paas_domain", "woowtech.io")
        services = request.env["woow_paas_platform.cloud_service"].sudo().search(
            [("workspace_id", "=", ws.id), ("state", "!=", "deleting")], order="name, id")
        data = []
        for svc in services:
            data.append({
                "id": svc.id,
                "name": svc.name,
                "template_slug": svc.template_id.slug or "",
                "template_name": svc.template_id.name or "",
                "release": svc.helm_release_name or "",
                "state": svc.state,
                "public_url": f"https://{svc.subdomain}.{domain}" if svc.subdomain else "",
            })
        return _json({"workspace": {"id": ws.id, "name": ws.name, "namespace": workspace_namespace(request.env, ws)},
                      "services": data})

    # ---------------------------------------------------------------- routes

    @route("/api/security-access/routes/check", type="http", auth="none", methods=["GET"], csrf=False)
    def cf_webgui_route_check(self, prefix=None, **kwargs):
        result = _auth("security-access:read")
        if isinstance(result, Response):
            return result
        prefix = (prefix or "").strip().lower()
        if not prefix:
            return _error("invalid_request", "prefix is required", 400)
        data = SecurityAccessController()._check_route_prefix(prefix).get("data") or {}
        return _json({"prefix": prefix, "available": bool(data.get("available")),
                      "reason": data.get("reason") or ""})

    def _sa_for_write(self, user, sa_id):
        """(sa, None) 或 (None, 錯誤 Response)：成員＋owner/admin＋訂閱可寫。

        回傳的 sa 綁在 token 擁有者身上（with_user(user).sudo()，同入口網站 Portal 的
        「保留原 uid＋sudo」）：auth='none' 的 request 沒有 uid，`_check_operation_allowed`
        的 `env.user.has_group` 與新路由的 create_uid 都要一個真的使用者
        （2026-11-18 lab 實測：沒綁使用者時寫入檢查一律失敗）。
        """
        sa = ha_api.HAIntegrationController()._get_sa_with_access(user, sa_id)
        if isinstance(sa, Response):
            return None, sa
        denied = ha_api._require_manage_role(user, sa.workspace_id)
        if denied:
            return None, denied
        sa = sa.with_user(user).sudo()
        try:
            sa._check_operation_allowed(operation="write")
        except Exception as exc:  # noqa: BLE001 — 上游丟 UserError／ValidationError，原文給使用者看
            return None, _error("not_writable", str(exc), 409)
        return sa, None

    @route("/api/security-access/accesses/<int:sa_id>/routes", type="http", auth="none", methods=["POST"], csrf=False)
    def cf_webgui_create_routes(self, sa_id, **kwargs):
        """一次建多條公開路由（全有或全無；一次 create ⇒ 一次 operator 同步）。"""
        result = _auth(ROUTES_SCOPE)
        if isinstance(result, Response):
            return result
        user, _token = result
        sa, failure = self._sa_for_write(user, sa_id)
        if failure:
            return failure

        try:
            body = json.loads(request.httprequest.get_data(as_text=True) or "{}")
        except ValueError:
            return _error("invalid_request", "Body must be JSON", 400)
        items = body.get("routes") if isinstance(body, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_ROUTES_PER_CALL:
            return _error("invalid_request", f"routes must be a list of 1 to {MAX_ROUTES_PER_CALL} items", 400)

        Route = sa.env["woow_paas_platform.security_access_route"]
        wanted, seen = [], set()
        for item in items:
            if not isinstance(item, dict):
                return _error("invalid_request", "each route must be an object", 400)
            prefix = str(item.get("subdomain_prefix") or "").strip().lower()
            service_url = str(item.get("service_url") or "").strip()
            fmt = Route._subdomain_prefix_error(prefix)
            if fmt:
                return _error("invalid_request", f"{prefix!r}: {fmt}", 400)
            if prefix in seen:
                return _error("invalid_request", f"{prefix!r} is listed twice", 400)
            seen.add(prefix)
            parsed = urlparse(service_url)
            if parsed.scheme not in SERVICE_SCHEMES or not parsed.hostname or len(service_url) > 512:
                return _error("invalid_request",
                              f"{prefix!r}: service_url must be an http(s)/tcp/ssh/rdp URL", 400)
            wanted.append({"subdomain_prefix": prefix, "service_url": service_url,
                           "http_host_header": bool(item.get("http_host_header", True))})

        sub = sa.subscription_id
        quota = sub.plan_id.sa_max_routes if sub and sub.plan_id else None
        if quota is not None and len(sa.route_ids) + len(wanted) > quota:
            return _error("quota_exceeded",
                          f"The plan allows {quota} route(s); {len(sa.route_ids)} already exist", 409)

        portal = SecurityAccessController()
        unavailable = {}
        for item in wanted:
            data = portal._check_route_prefix(item["subdomain_prefix"]).get("data") or {}
            if not data.get("available"):
                unavailable[item["subdomain_prefix"]] = data.get("reason") or "taken"
        if unavailable:
            return _error("unavailable", "Some names are not available", 409, prefixes=unavailable)

        try:
            with request.env.cr.savepoint():
                created = Route.create([{
                    "security_access_id": sa.id,
                    "subdomain_prefix": item["subdomain_prefix"],
                    "service_url": item["service_url"],
                    "http_host_header": item["http_host_header"],
                    "is_protected": False,
                } for item in wanted])
        except ValidationError as exc:
            return _error("unavailable", str(exc), 409, prefixes={})
        except Exception as exc:  # noqa: BLE001 — operator／Cloudflare 失敗：savepoint 已回捲 DB
            _logger.exception("[cf-webgui] creating routes for SA %s failed", sa.id)
            return _error("sync_failed", f"Cloudflare update failed: {exc}", 502)
        _logger.info("[cf-webgui] SA %s: %s route(s) created by user %s: %s",
                     sa.id, len(created), user.id, created.mapped("subdomain_prefix"))
        return _json({"routes": [r.to_dict() for r in created], "access": sa.to_dict()})

    @route("/api/security-access/accesses/<int:sa_id>/routes/<int:route_id>",
           type="http", auth="none", methods=["DELETE"], csrf=False)
    def cf_webgui_delete_route(self, sa_id, route_id, **kwargs):
        result = _auth(ROUTES_SCOPE)
        if isinstance(result, Response):
            return result
        user, _token = result
        sa, failure = self._sa_for_write(user, sa_id)
        if failure:
            return failure
        target = sa.route_ids.filtered(lambda r: r.id == route_id)
        if not target:
            return _error("Not Found", "Route not found", 404)
        hostname = target.hostname
        try:
            with request.env.cr.savepoint():
                target.unlink()
        except Exception as exc:  # noqa: BLE001
            _logger.exception("[cf-webgui] deleting route %s of SA %s failed", route_id, sa.id)
            return _error("sync_failed", f"Cloudflare update failed: {exc}", 502)
        _logger.info("[cf-webgui] SA %s: route %s (%s) deleted by user %s", sa.id, route_id, hostname, user.id)
        return _json({"deleted": True})
