# odoo shell：用平台自己的建立流程（service_ops.plan_create / write_create，跟網站同一條）開一台 woowtechbot。
# woowtechbot 範本的 bot.adminEmail 是必填欄位（平台在寫入前就檢查），所以建立時就帶進 values（create_service.py 是建立後才合併）。
#   env: WS_NAME, SVC_NAME, ADMIN_EMAIL, DRY=1（預設，只算不寫）
# 印出：workspace id／ws_hash、namespace、service id、release、subdomain。2026-11-23 woowtechbot 上架本機 PaaS 實測用。
import json, os
from odoo.addons.woow_paas_platform.services import service_ops

DRY = os.environ.get("DRY", "1") == "1"
WS_NAME = os.environ["WS_NAME"]
SVC_NAME = os.environ["SVC_NAME"]
ADMIN_EMAIL = os.environ["ADMIN_EMAIL"]

admin = env.ref("base.user_admin")
uenv = env(user=admin.id)
tmpl = uenv["woow_paas_platform.cloud_app_template"].sudo().search([("slug", "=", "woowtechbot")], limit=1)
assert tmpl and not tmpl.is_hidden and tmpl.is_active, "woowtechbot template is not listed"
plan_id = tmpl.subscription_plan_ids.sorted("id")[:1].id
Workspace = uenv["woow_paas_platform.workspace"]
ws = Workspace.search([("name", "=", WS_NAME)], limit=1)
if not ws:
    ws = Workspace.create({"name": WS_NAME, "owner_id": admin.id,
                          "description": "woowtechbot 上架本機 PaaS 實測（2026-11-23）"})
print("workspace", ws.id, ws.ws_hash)
plan = service_ops.plan_create(uenv, ws, template_id=tmpl.id, plan_id=plan_id, name=SVC_NAME,
                               values={"bot.adminEmail": ADMIN_EMAIL})  # 跟網站表單一樣是 spec 的點分鍵
print("namespace", plan.helm_namespace, "template", tmpl.id, tmpl.helm_chart_name, tmpl.helm_chart_version, "plan", plan_id)
if DRY:
    merged = plan.merged_values
    print("values", json.dumps({k: merged.get(k) for k in ("image", "resources", "persistence", "bot")}, ensure_ascii=False)[:1500])
    env.cr.rollback()
    print("DRY run: rolled back")
else:
    res = service_ops.write_create(uenv, ws, plan)
    svc = res.service
    env.cr.commit()
    print("created service", svc.id, svc.helm_release_name, svc.helm_namespace, svc.state, "| subdomain", svc.subdomain)
