# odoo shell：用平台自己的刪除流程刪服務（跟網站 /woow 的 delete 同一條）：
#   訂閱閘 _check_operation_allowed('delete') → service_ops.check_delete_service → 列鎖 → delete_service_locked
#   （轉 deleting → operator 卸載 release、清 Cloudflare 路由與 DNS → 刪服務紀錄；PVC 由 operator 標保留期）。
#   env: SERVICE_IDS="44,45"（逗號分隔）, DRY=1（預設：只列出，不動）
# 2026-11-24 MCP 改釘 P3 的全新部署實測用完清掉。
import os

from odoo.addons.woow_paas_platform.services import service_ops
from odoo.addons.woow_paas_platform.services.paas_operator import get_paas_operator_client

DRY = os.environ.get("DRY", "1") == "1"
IDS = [int(x) for x in os.environ["SERVICE_IDS"].split(",") if x.strip()]

admin = env.ref("base.user_admin")
uenv = env(user=admin.id)
client = get_paas_operator_client(uenv)
for svc in uenv["woow_paas_platform.cloud_service"].browse(IDS).exists():
    print(f"service {svc.id} {svc.name} state={svc.state} release={svc.helm_release_name} ns={svc.helm_namespace}")
    if DRY:
        continue
    svc._check_operation_allowed(operation="delete")
    service_ops.check_delete_service(uenv, svc, client=client)
    if not svc._try_lock_lifecycle_rows():
        print("   skip: another operation is in progress")
        env.cr.rollback()
        continue
    service_ops.delete_service_locked(uenv, svc, client)
    env.cr.commit()
    print("   deleted")
if DRY:
    env.cr.rollback()
    print("DRY run: nothing changed")
