#!/usr/bin/env python3
"""把 Helm chart .tgz「原封不動」推到 GHCR，但 manifest 不帶 org.opencontainers.image.description。

為什麼：hermes-agent 0.4.9 的 Chart.yaml 說明含大量中文，`helm push` 會把它放進 manifest annotation，
GHCR 對這個 manifest 一律回 500（2026-11-15 實測；英文為主的長說明如 omnigent 1510 字可以）。
chart 本體（layer＝原 tgz）與 config（Chart.yaml 的 JSON）照舊，`helm pull`／`helm install` 行為不變。
用法：GHCR_TOKEN=$(gh auth token) python3 tools/oci-push-chart-nodesc.py <chart.tgz> <oci://ghcr.io/owner/path>
"""
import base64, hashlib, io, json, sys, tarfile, urllib.parse, urllib.request, os, datetime

tgz, dest = sys.argv[1], sys.argv[2]
assert dest.startswith("oci://ghcr.io/")
repo_base = dest[len("oci://ghcr.io/"):].strip("/")
data = open(tgz, "rb").read()
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
    member = next(m for m in tf.getmembers() if m.name.count("/") == 1 and m.name.endswith("/Chart.yaml"))
    import yaml
    meta = yaml.safe_load(tf.extractfile(member).read())
name, version = meta["name"], meta["version"]
repo = f"{repo_base}/{name}"
config = json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode()
token_basic = base64.b64encode(f"WOOWTECH:{os.environ['GHCR_TOKEN']}".encode()).decode()
req = urllib.request.Request(f"https://ghcr.io/token?service=ghcr.io&scope=repository:{repo}:pull,push",
                             headers={"Authorization": f"Basic {token_basic}"})
bearer = json.load(urllib.request.urlopen(req))["token"]
H = {"Authorization": f"Bearer {bearer}"}

def put_blob(blob):
    dg = "sha256:" + hashlib.sha256(blob).hexdigest()
    head = urllib.request.Request(f"https://ghcr.io/v2/{repo}/blobs/{dg}", method="HEAD", headers=H)
    try:
        urllib.request.urlopen(head); return dg, len(blob)          # already there
    except urllib.error.HTTPError as e:
        if e.code != 404: raise
    r = urllib.request.urlopen(urllib.request.Request(f"https://ghcr.io/v2/{repo}/blobs/uploads/", data=b"", method="POST", headers=H))
    loc = urllib.parse.urljoin("https://ghcr.io/", r.headers["Location"])
    loc += ("&" if "?" in loc else "?") + "digest=" + urllib.parse.quote(dg)
    urllib.request.urlopen(urllib.request.Request(loc, data=blob, method="PUT", headers={**H, "Content-Type": "application/octet-stream"}))
    return dg, len(blob)

cdg, clen = put_blob(config)
ldg, llen = put_blob(data)
manifest = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {"mediaType": "application/vnd.cncf.helm.config.v1+json", "digest": cdg, "size": clen},
            "layers": [{"mediaType": "application/vnd.cncf.helm.chart.content.v1.tar+gzip", "digest": ldg, "size": llen}],
            "annotations": {"org.opencontainers.image.title": name, "org.opencontainers.image.version": version,
                            "org.opencontainers.image.created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}}
body = json.dumps(manifest, separators=(",", ":")).encode()
r = urllib.request.urlopen(urllib.request.Request(f"https://ghcr.io/v2/{repo}/manifests/{version}", data=body, method="PUT",
                                                  headers={**H, "Content-Type": "application/vnd.oci.image.manifest.v1+json"}))
print(f"Pushed: ghcr.io/{repo}:{version} manifest={r.headers.get('Docker-Content-Digest')} layer={ldg} (tgz bytes unchanged)")
