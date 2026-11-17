#!/usr/bin/env python3
"""把 Cloudflare tunnel 裡某個 public hostname 的 origin 改成新的 service 網址（其餘設定原樣保留）。

用本機 PaaS 的 Cloudflare token（~/woow_tech_credential/cf-paas-lab.env 的 CF_API_TOKEN；不印出）。
用法：tunnel_origin.py <account> <tunnel_id> <hostname> <new_service_url>   （new_service_url 省略＝只讀）
"""
import json
import os
import re
import sys
import urllib.request

acct, tunnel, host = sys.argv[1:4]
new_service = sys.argv[4] if len(sys.argv) > 4 else None
env = {}
for line in open(os.path.expanduser("~/woow_tech_credential/cf-paas-lab.env")):
    m = re.match(r'^\s*(?:export\s+)?([A-Z_]+)=(.*)$', line.strip())
    if m:
        env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/cfd_tunnel/{tunnel}/configurations"
headers = {"Authorization": f"Bearer {env['CF_API_TOKEN']}", "Content-Type": "application/json",
           "User-Agent": "Mozilla/5.0 paas-lab-migrate"}


def call(method, body=None):
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {json.loads(e.read()).get('errors')}")


cur = call("GET")["result"]
config = cur["config"]
rules = config.get("ingress") or []
print("before:", [(r.get("hostname"), r.get("service")) for r in rules], "version", cur.get("version"))
if new_service:
    hits = [r for r in rules if r.get("hostname") == host]
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one rule for {host}, found {len(hits)}")
    hits[0]["service"] = new_service
    res = call("PUT", {"config": config})["result"]
    print("after: ", [(r.get("hostname"), r.get("service")) for r in res["config"]["ingress"]], "version", res.get("version"))
