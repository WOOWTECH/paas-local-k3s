# odoo shell：把指定服務走平台自己的「重新部署」（action_redeploy，管理員）換到範本目前釘的 chart／映像。
# 只適用 deployment_policy=template 的服務（pinned 的會照服務自己的釘版，不會跟著範本走）。
# 平台會把範本的新映像寫回服務的 helm_values（#1408）、helm upgrade（reset_values、PVC 保留），
# 再由 cron 輪詢到就緒、核對映像（redeploy_verify_pending）。MCP 的 config.json 是 write-only-if-absent，管理員密碼不會被洗掉。
#   env: SERVICE_IDS="18,19"（逗號分隔）, DRY=1（預設：只印目前與目標，不動）
# 2026-11-24 MCP 改釘 P3（4e8da3f0）時，換本機 7 台 lab-mcp-* 用。
import json, os

DRY = os.environ.get("DRY", "1") == "1"
IDS = [int(x) for x in os.environ["SERVICE_IDS"].split(",") if x.strip()]

admin = env.ref("base.user_admin")
Svc = env(user=admin.id)["woow_paas_platform.cloud_service"]
for svc in Svc.browse(IDS):
    target = svc._resolve_deployment_target()
    cur = (svc.sudo().helm_values or {}).get("image", {}) if isinstance(svc.sudo().helm_values, dict) else {}
    want = (target.get("image_values") or {}).get("image", {}) if isinstance(target.get("image_values"), dict) else {}
    print(f"service {svc.id} {svc.name} state={svc.state} policy={svc.deployment_policy} "
          f"chart {svc.helm_chart_version}->{target.get('version')} "
          f"image {str(cur.get('tag'))[:12]}->{str(want.get('tag') or '(template)')[:12]}")
    if svc.deployment_policy != "template":
        print("   skip: not following the template")
        continue
    if DRY:
        continue
    res = svc.action_redeploy()
    env.cr.commit()
    print(f"   redeploy -> state={svc.state} helm_revision={svc.helm_revision} "
          f"{'(queued: ' + res['params']['title'] + ')' if isinstance(res, dict) and res.get('params') else ''}")
if DRY:
    env.cr.rollback()
    print("DRY run: nothing changed")
