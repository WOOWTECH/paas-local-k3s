# odoo shell：用平台自己的建立流程（service_ops.plan_create / write_create，跟網站同一條）開一個服務，
# 同一個交易裡把管理員 helm_values（OVERRIDES_JSON）深合併進去。工作區不存在就建（擁有者 admin）。
#   env: WS_NAME, SVC_NAME, TEMPLATE_SLUG, OVERRIDES_JSON（可省）, DRY=1（預設，只算不寫）, OUT_SECRET（一次性憑證寫到這個檔，可省）,
#        WS_DESC（工作區不存在時新建用的說明，可省）
# 印出：workspace id／ws_hash、namespace、service id、release。從 pi5 的 create_service_pi5.py 一般化而來（2026-11-17）。
import json, os
from odoo.addons.woow_paas_platform.services import service_ops

DRY = os.environ.get("DRY", "1") == "1"
WS_NAME = os.environ["WS_NAME"]
SVC_NAME = os.environ["SVC_NAME"]
SLUG = os.environ["TEMPLATE_SLUG"]
OVERRIDES = json.loads(os.environ.get("OVERRIDES_JSON") or "{}")


def deep_merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


admin = env.ref("base.user_admin")
uenv = env(user=admin.id)
tmpl = uenv["woow_paas_platform.cloud_app_template"].sudo().with_context(active_test=False).search([("slug", "=", SLUG)], limit=1)
assert tmpl, f"template {SLUG} not found"
plan_id = tmpl.subscription_plan_ids[:1].id
Workspace = uenv["woow_paas_platform.workspace"]
ws = Workspace.search([("name", "=", WS_NAME)], limit=1)
if not ws:
    ws = Workspace.create({"name": WS_NAME, "owner_id": admin.id,
                          "description": os.environ.get("WS_DESC") or "Odoo App 推播測試環境，從本機 k3s 手架的部署搬進 PaaS 管理（2026-11-17）"})
print("workspace", ws.id, ws.ws_hash)
# 一般建立流程拒絕 hidden 範本（#336）。這兩個本機範本刻意藏起來不讓租戶開，所以只在這個交易裡暫時打開、
# commit 前再藏回去：其他連線看不到中間狀態。
was_hidden = tmpl.is_hidden
if was_hidden:
    tmpl.is_hidden = False
plan = service_ops.plan_create(uenv, ws, template_id=tmpl.id, plan_id=plan_id, name=SVC_NAME, values={})
print("namespace", plan.helm_namespace, "template", tmpl.id, tmpl.helm_chart_version, "plan", plan_id)
if DRY:
    print("values", json.dumps(deep_merge(plan.merged_values, OVERRIDES), ensure_ascii=False)[:1500])
    env.cr.rollback()
    print("DRY run: rolled back")
else:
    res = service_ops.write_create(uenv, ws, plan)
    svc = res.service
    if OVERRIDES:
        svc.sudo()._apply_helm_values(deep_merge(svc.sudo()._helm_values_dict(), OVERRIDES))
    if was_hidden:
        tmpl.is_hidden = True
    env.cr.commit()
    if os.environ.get("OUT_SECRET") and res.one_time_credentials:
        with open(os.environ["OUT_SECRET"], "w") as f:
            json.dump(res.one_time_credentials, f)
    print("created service", svc.id, svc.helm_release_name, svc.helm_namespace, svc.state, "| subdomain", svc.subdomain)
