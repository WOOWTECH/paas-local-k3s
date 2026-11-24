#!/usr/bin/env python3
"""本機 PaaS 的 MCP 服務實測（2026-11-24，MCP 改釘 P3 時寫）：每台走公開網址檢查
① /healthz ② 管理介面登入 ③ /api/health ④ /api/tools ⑤ MCP 協定（initialize → tools/list，用完 DELETE session），
並印出 pod 實際跑的映像 digest。

用法：LAB_TEST_PW=… python3 tools/check_mcp_services.py <namespace>/<release>=<subdomain> [...]
  - 管理員密碼從環境變數 LAB_TEST_PW 讀（本機測試服務的共用測試密碼；MCP Headscale 不是這組，登入會 401，照實列出）。
  - MCP 共用權杖從 pod 的 /data/config.json（mcp_auth_token）讀，只拿來組網址，不印出。
  - 權杖在網址路徑裡（/private_<token>/mcp），輸出裡一律遮掉。
"""
import json
import os
import subprocess
import sys

import requests

DOMAIN = os.environ.get("LAB_PAAS_DOMAIN", "woowtech.io")
CTX = os.environ.get("KUBE_CONTEXT", "default")
UA = {"User-Agent": "woow-lab-mcp-check/1.0"}  # Cloudflare 會擋 python 預設 UA（1010）
PW = os.environ.get("LAB_TEST_PW", "")
TIMEOUT = 60
SECRETS = []  # 讀到的權杖：輸出前一律遮掉（例外訊息可能帶著網址）


def kubectl(*args):
    return subprocess.run(["kubectl", "--context", CTX, *args], check=True, capture_output=True, text=True).stdout


def pod_facts(ns, release):
    pods = json.loads(kubectl("-n", ns, "get", "pods", "-l", f"app.kubernetes.io/instance={release}", "-o", "json"))["items"]
    pods = [p for p in pods if p["status"].get("phase") == "Running"]
    if not pods:
        return None, None
    pod = pods[0]
    st = pod["status"]["containerStatuses"][0]
    token = kubectl("-n", ns, "exec", pod["metadata"]["name"], "-c", st["name"], "--", "python3", "-c",
                    "import json;print(json.load(open('/data/config.json')).get('mcp_auth_token',''))").strip()
    if token:
        SECRETS.append(token)
    return {"pod": pod["metadata"]["name"], "node": pod["spec"].get("nodeName"),
            "image": st["image"].split("@")[0].rsplit("/", 1)[-1][:40], "digest": st["imageID"].rsplit("@", 1)[-1][:19],
            "restarts": st.get("restartCount")}, token


def sse_or_json(resp):
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return None
    return resp.json() if resp.content else None


def mcp_probe(base, token):
    url = f"{base}/private_{token}/mcp"
    h = {**UA, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    r = requests.post(url, headers=h, timeout=TIMEOUT, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "woow-lab-mcp-check", "version": "1.0"}}})
    out = {"initialize": r.status_code}
    if r.status_code != 200:
        return out
    init = sse_or_json(r) or {}
    info = (init.get("result") or {}).get("serverInfo") or {}
    out["server"] = f"{info.get('name')} {info.get('version')}"
    sid = r.headers.get("mcp-session-id")
    if sid:
        h["mcp-session-id"] = sid
    requests.post(url, headers=h, timeout=TIMEOUT, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    r = requests.post(url, headers=h, timeout=TIMEOUT, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    out["tools/list"] = r.status_code
    if r.status_code == 200:
        tools = ((sse_or_json(r) or {}).get("result") or {}).get("tools") or []
        out["tools"] = len(tools)
        out["sample"] = [t.get("name") for t in tools[:4]]
    if sid:
        out["delete"] = requests.delete(url, headers=h, timeout=TIMEOUT).status_code
    return out


def check(spec):
    target, sub = spec.split("=", 1)
    ns, release = target.split("/", 1)
    base = f"https://{sub}.{DOMAIN}"
    res = {"service": release, "url": base}
    facts, token = pod_facts(ns, release)
    res["pod"] = facts
    r = requests.get(f"{base}/healthz", headers=UA, timeout=TIMEOUT)
    res["healthz"] = [r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:80]]
    s = requests.Session()
    s.headers.update(UA)
    r = s.post(f"{base}/api/auth/login", json={"password": PW}, timeout=TIMEOUT)
    res["login"] = r.status_code
    if r.status_code == 200:
        h = s.get(f"{base}/api/health", timeout=TIMEOUT)
        if h.status_code == 200:
            j = h.json()
            res["health"] = {"overall": j.get("overall_status"), "mcp": (j.get("mcp_server") or {}).get("healthy"),
                             "target": (j.get("target_app") or {}).get("healthy"), "version": j.get("version")}
        else:
            res["health"] = h.status_code
        t = s.get(f"{base}/api/tools", timeout=TIMEOUT)
        res["admin_tools"] = {k: t.json().get(k) for k in ("total", "enabled")} if t.status_code == 200 else t.status_code
        s.post(f"{base}/api/auth/logout", timeout=TIMEOUT)
    res["mcp"] = mcp_probe(base, token) if token else "no token in config.json"
    return res


if __name__ == "__main__":
    ok = True
    for spec in sys.argv[1:]:
        try:
            res = check(spec)
        except Exception as exc:  # noqa: BLE001 — 實測工具：一台失敗不影響其他台
            res, ok = {"service": spec, "error": f"{type(exc).__name__}: {exc}"[:300]}, False
        line = json.dumps(res, ensure_ascii=False)
        for secret in SECRETS:  # 只遮權杖；密碼從不輸出（遮密碼反而會把含同字串的節點名遮掉、洩漏密碼樣式）
            line = line.replace(secret, "***")
        print(line)
    sys.exit(0 if ok else 1)
