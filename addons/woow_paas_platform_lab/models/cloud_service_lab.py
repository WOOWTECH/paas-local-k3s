"""Lab overlay：Cloudflare Tunnel WebGUI 也要拿到 apiserver 真實位址（列出同工作區的服務要連 K8s API）。

上游 `_inject_apiserver_cidrs` 只認 open-design／hermes-agent／omnigent 三個 slug（寫死在 path_map）。
cf-tunnel-webgui／apporo-cf-tunnel-webgui 的 chart 用 `networkPolicy.apiServerCidrs`（同 open-design 的鍵名），值取自
`woow_paas_platform.apiserver_cidrs`（lab：10.43.0.1/32,192.168.2.10/32；kube-router 在 DNAT 之後比對 egress）。
"""
from odoo import models
from odoo.addons.woow_paas_platform.models.cloud_service import CloudService as _UpstreamCloudService

CF_WEBGUI_SLUGS = ("cf-tunnel-webgui", "apporo-cf-tunnel-webgui")


class CloudServiceLab(models.Model):
    _inherit = "woow_paas_platform.cloud_service"

    @staticmethod
    def _inject_apiserver_cidrs(values, template_slug, cidrs):
        if template_slug in CF_WEBGUI_SLUGS and cidrs:
            values.setdefault("networkPolicy", {})["apiServerCidrs"] = list(cidrs)
            return values
        return _UpstreamCloudService._inject_apiserver_cidrs(values, template_slug, cidrs)
