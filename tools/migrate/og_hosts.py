# 唯讀：正式站 Omnigent 上名稱含關鍵字（預設 pi5）的主機與狀態（沿用本機 omni CLI 的登入；不印 token）
import json, sys, urllib.request
from omnigent.chat import _remote_headers
BASE = "https://omnigent.woowtech.io"
key = (sys.argv[1] if len(sys.argv) > 1 else "pi5").lower()
h = dict(_remote_headers(BASE, host_id=None)); h["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) omnigent-cli/1.0"
hosts = json.loads(urllib.request.urlopen(urllib.request.Request(BASE + "/v1/hosts", headers=h), timeout=30).read())["hosts"]
for x in hosts:
    if key in (x.get("name") or "").lower():
        print(x.get("name"), "|", x.get("status"), "| last_seen", x.get("last_seen"), "| host_id", (x.get("host_id") or "")[:12])
