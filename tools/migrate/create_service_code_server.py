# odoo shell：在 PaaS「本機 k3s 服務」工作區建 code-server 服務 code-server-codex（走平台自己的 service_ops 建立流程），
# 同一個交易裡把管理員 helm_values 補上：放 cluster7、照舊接正式站 Omnigent、主機名與舊 pi5 相同。
# DRY=1（預設）只算不寫；DRY=0 才 commit。一次性憑證寫到 OUT_SECRET 檔（不印出）。
import json, os
GIT_USER = os.environ.get("GIT_USER", "")
from odoo.addons.woow_paas_platform.services import service_ops

DRY = os.environ.get("DRY", "1") == "1"
WS_NAME = "本機 k3s 服務"
SVC_NAME = "code-server-codex"
OVERRIDES = {
    # 小主機裡只有 cluster5 還能預留 1Gi；舊的也是 requests 1Gi（方案會給 1536Mi）。
    "nodeSelector": {"kubernetes.io/arch": "amd64", "kubernetes.io/hostname": "woowtechcluster5"},
    "codeServer": {"resources": {"requests": {"memory": "1Gi"}}, "locale": "zh-tw", "loginI18n": True},
    # 沿用舊 code-server-codex 的設定（API key／git token 舊的本來就是空的）
    "pi": {"defaultProvider": "openai-codex", "openrouterDefaultModel": "moonshotai/kimi-k2.6"},
    "git": {"tokenHosts": ["https://github.com"], "tokenUsername": GIT_USER},
    "claude": {"claudeAiMcpServers": False},
    "timezone": "Asia/Taipei",
}

def deep_merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out

admin = env.ref("base.user_admin")
uenv = env(user=admin.id)
tmpl = uenv["woow_paas_platform.cloud_app_template"].sudo().search([("slug", "=", "code-server")], limit=1)
print("template", tmpl.id, tmpl.name, "chart", tmpl.helm_chart_version, "max_per_partner", tmpl.max_per_partner)
for p in tmpl.subscription_plan_ids:
    print("  plan", p.id, p.name)
Workspace = uenv["woow_paas_platform.workspace"]
ws = Workspace.search([("name", "=", WS_NAME)], limit=1)
if not ws:
    ws = Workspace.create({"name": WS_NAME, "owner_id": admin.id,
                          "description": "從本機 k3s 直接部署搬進 PaaS 管理的服務（2026-11-16 起）"})
    print("workspace created", ws.id, ws.ws_hash)
else:
    print("workspace exists", ws.id, ws.ws_hash)
plan_id = int(os.environ.get("PLAN_ID") or tmpl.subscription_plan_ids[:1].id)
plan = service_ops.plan_create(uenv, ws, template_id=tmpl.id, plan_id=plan_id, name=SVC_NAME, values={})
final = deep_merge(plan.merged_values, OVERRIDES)
print("namespace", plan.helm_namespace, "plan_id", plan_id)
print("values", json.dumps({k: final[k] for k in ("nodeSelector", "codeServer", "pi", "git", "claude", "timezone", "image", "persistence") if k in final}, ensure_ascii=False))
if DRY:
    env.cr.rollback()
    print("DRY run: rolled back")
else:
    res = service_ops.write_create(uenv, ws, plan)
    svc = res.service
    svc.sudo()._apply_helm_values(deep_merge(svc.sudo()._helm_values_dict(), OVERRIDES))
    env.cr.commit()
    with open(os.environ["OUT_SECRET"], "w") as f:
        json.dump(res.one_time_credentials, f)
    print("created service", svc.id, svc.helm_release_name, svc.helm_namespace, svc.state)
