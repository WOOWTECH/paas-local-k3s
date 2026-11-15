#!/usr/bin/env python3
"""把 Job YAML 裡 lab-addon volume 的 configMap.items 依 addons/woow_paas_platform_lab 的實際檔案重新產生後印出。
用法：python3 tools/with-lab-addon-items.py jobs/lab-overlay-update.yaml [--configmap NAME] | kubectl --context default apply -f -
（key 規則與 tools/post-render-lab-addon.py 相同：相對路徑的 / 換成 .）"""
import pathlib, sys, yaml
HERE = pathlib.Path(__file__).resolve().parent
ADDON = HERE.parent / "addons" / "woow_paas_platform_lab"
items = [{"key": p.relative_to(ADDON).as_posix().replace("/", "."), "path": p.relative_to(ADDON).as_posix()}
         for p in sorted(ADDON.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
cm_name = sys.argv[sys.argv.index("--configmap") + 1] if "--configmap" in sys.argv else None
docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if d]
for d in docs:
    for v in d["spec"]["template"]["spec"].get("volumes", []):
        if v.get("name") == "lab-addon":
            v["configMap"]["items"] = items
            if cm_name:
                v["configMap"]["name"] = cm_name
sys.stdout.write(yaml.safe_dump_all(docs, sort_keys=False, allow_unicode=True))
