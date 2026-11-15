#!/usr/bin/env python3
"""通用 Helm post-renderer：所有工作負載加 required nodeAffinity，避開筆電與 TUF。
給沒有 affinity／nodeSelector 參數的 chart 用（例：woow-mcp-gateway 0.2.0）。
TUF：pod 網路不通（連 CoreDNS 都逾時）；筆電：記憶體 requests 已滿。"""
import sys, yaml
AVOID = ["woowtechcluster1-aorus-15p-xd", "woowtech-ai-coder-asus-tuf-gaming-f15-fx507zu4-fx507zu4"]
def pod_spec(d):
    k = d.get("kind")
    if k == "CronJob": return d["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    if k in ("Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet"): return d["spec"]["template"]["spec"]
    return None
docs = [d for d in yaml.safe_load_all(sys.stdin.read()) if d]
for d in docs:
    ps = pod_spec(d)
    if ps is None: continue
    terms = ps.setdefault("affinity", {}).setdefault("nodeAffinity", {}).setdefault(
        "requiredDuringSchedulingIgnoredDuringExecution", {}).setdefault("nodeSelectorTerms", [])
    expr = {"key": "kubernetes.io/hostname", "operator": "NotIn", "values": AVOID}
    if not terms: terms.append({"matchExpressions": [expr]})
    else:
        for t in terms: t.setdefault("matchExpressions", []).append(expr)
sys.stdout.write(yaml.safe_dump_all(docs, sort_keys=False, allow_unicode=True))
