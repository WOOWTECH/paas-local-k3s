# pi5（服務 33）pi-web 記憶體 requests 1536Mi → 1Gi（cluster7 只剩約 1.5Gi 可預留；limits 3Gi 不變），再走平台 Redeploy。
import json
admin = env.ref("base.user_admin")
svc = env["woow_paas_platform.cloud_service"].browse(33)
lease = svc.init_lease_until if "init_lease_until" in svc._fields else None
print("state", svc.state, "| init lease until", lease)
vals = svc._helm_values_dict()
print("before", json.dumps(vals["piWeb"]["resources"]))
vals["piWeb"]["resources"]["requests"]["memory"] = "1Gi"
svc._apply_helm_values(vals)
env.cr.commit()
print("after ", json.dumps(svc._helm_values_dict()["piWeb"]["resources"]))
res = svc.with_user(admin).action_redeploy()
env.cr.commit()
print("redeploy ->", json.dumps(res, ensure_ascii=False, default=str)[:400])
print("state now", svc.state)
