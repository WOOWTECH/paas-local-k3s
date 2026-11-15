#!/usr/bin/env python3
"""Helm post-renderer：把 addons/woow_paas_platform_lab 以 ConfigMap 掛進平台 web／cron 的 odoo 容器。

為什麼：woow-odoo chart 沒有 extraVolumes／extraAddons（platform 的 addons_path 只有 core 與 image 內建的 /opt/woow/addons），
而使用者決定映像一律從 JCR 原樣複製、不另外 build。把 overlay addon 掛在 /opt/woow/addons/woow_paas_platform_lab
（image 目錄下新增一個 mountpoint，不遮住既有 addon）就能讓 Odoo 當成內建 addon 載入。

用法：helm ... --post-renderer tools/post-render-lab-addon.py
  stdin  = helm 渲染出的 manifests
  stdout = 同一份 manifests ＋ 一個 ConfigMap（隨 release 一起管理）＋ Deployment 的 volume／volumeMount
"""
import os, sys, pathlib, yaml

HERE = pathlib.Path(__file__).resolve().parent
ADDON_DIR = HERE.parent / "addons" / "woow_paas_platform_lab"
ADDON = ADDON_DIR.name
CM_NAME = "woow-paas-platform-lab-addon"
VOL = "lab-addon"
MOUNT = f"/opt/woow/addons/{ADDON}"          # = woow-odoo.imageAddonsDirs/<addon>
TARGET_DEPLOYMENTS = {"paas-odoo-platform", "paas-odoo-platform-cron"}

def key_for(rel: str) -> str:
    return rel.replace("/", ".")              # ConfigMap key 只能 [-._a-zA-Z0-9]

def addon_files():
    for p in sorted(ADDON_DIR.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            yield p.relative_to(ADDON_DIR).as_posix(), p.read_text()

def main():
    docs = [d for d in yaml.safe_load_all(sys.stdin.read()) if d]
    ns = None
    files = list(addon_files())
    items = [{"key": key_for(rel), "path": rel} for rel, _ in files]
    for d in docs:
        if d.get("kind") != "Deployment" or d["metadata"]["name"] not in TARGET_DEPLOYMENTS:
            continue
        ns = ns or d["metadata"].get("namespace")
        spec = d["spec"]["template"]["spec"]
        vols = spec.setdefault("volumes", [])
        if not any(v.get("name") == VOL for v in vols):
            vols.append({"name": VOL, "configMap": {"name": CM_NAME, "items": items}})
        for kind in ("initContainers", "containers"):
            for c in spec.get(kind, []) or []:
                if c.get("name") == "nginx":
                    continue                   # 只有跑 odoo 的容器需要
                mounts = c.setdefault("volumeMounts", [])
                if not any(m.get("mountPath") == MOUNT for m in mounts):
                    mounts.append({"name": VOL, "mountPath": MOUNT, "readOnly": True})
    cm = {"apiVersion": "v1", "kind": "ConfigMap",
          "metadata": {"name": CM_NAME, **({"namespace": ns} if ns else {}),
                       "labels": {"app.kubernetes.io/part-of": "woow-odoo", "woow.paas/lab-overlay": "true"}},
          "data": {key_for(rel): content for rel, content in files}}
    docs.append(cm)
    sys.stdout.write(yaml.safe_dump_all(docs, sort_keys=False, allow_unicode=True, default_flow_style=False))

if __name__ == "__main__":
    main()
