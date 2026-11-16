#!/usr/bin/env python3
"""把 Job YAML 的 addon volume／volumeMount 依 addons/ 的實際內容重新產生後印出（規則在 tools/lab_addons.py）。
用法：python3 tools/with-lab-addon-items.py jobs/lab-overlay-update.yaml [--configmap-suffix -next] [--install-extras] | kubectl --context default apply -f -
  --configmap-suffix  改掛 <ConfigMap 名稱><suffix>（更新腳本先套的「下一版」）
  --install-extras    在 odoo 指令加上 -i <lab-extra-modules.txt 的模組>（已安裝的 Odoo 會跳過）
（舊參數 --configmap NAME 仍可用，只對 overlay 生效。）"""
import sys
import yaml
import lab_addons as L

argv = sys.argv[1:]
suffix = argv[argv.index("--configmap-suffix") + 1] if "--configmap-suffix" in argv else ""
legacy_cm = argv[argv.index("--configmap") + 1] if "--configmap" in argv else None
install_extras = "--install-extras" in argv
addons = L.addon_names()
docs = [d for d in yaml.safe_load_all(open(argv[0])) if d]
for d in docs:
    spec = d["spec"]["template"]["spec"]
    vols = [v for v in spec.get("volumes", []) if not v.get("name", "").startswith("lab-addon")]
    for a in addons:
        name = legacy_cm if (legacy_cm and a == L.OVERLAY) else L.cm_name(a, suffix)
        vols.append({"name": L.vol_name(a), "configMap": {"name": name, "items": L.items(a)}})
    spec["volumes"] = vols
    for c in spec.get("containers", []):
        if not any(m.get("name", "").startswith("lab-addon") for m in c.get("volumeMounts", [])):
            continue                          # 只改原本就掛 overlay 的容器
        mounts = [m for m in c["volumeMounts"] if not m.get("name", "").startswith("lab-addon")]
        mounts += [{"name": L.vol_name(a), "mountPath": L.mount_path(a), "readOnly": True} for a in addons]
        c["volumeMounts"] = mounts
        cmd = c.get("command") or []
        extras = L.extra_modules()
        if install_extras and extras and cmd and cmd[0] == "odoo" and "-i" not in cmd:
            at = cmd.index("-u") if "-u" in cmd else len(cmd)
            c["command"] = cmd[:at] + ["-i", ",".join(extras)] + cmd[at:]
sys.stdout.write(yaml.safe_dump_all(docs, sort_keys=False, allow_unicode=True))
