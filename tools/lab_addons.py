"""本 repo addons/ 底下要掛進平台的 addon（overlay＋vendored 模組）：檔案、ConfigMap、volume 的唯一來源。
post-render-lab-addon.py（helm）、with-lab-addon-items.py（Job）、lab-overlay-update.sh 共用，規則只寫在這裡。
- 每個 addon 一個 ConfigMap、掛在 /opt/woow/addons/<addon>（image 內建 addons 目錄下的新 mountpoint，不遮住既有 addon）
- ConfigMap key＝相對路徑把 / 換成 .；非 UTF-8 檔（圖示等）放 binaryData
- overlay 沿用原本的 ConfigMap／volume 名稱（helm release 早就在管）"""
import base64
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADDONS_DIR = ROOT / "addons"
OVERLAY = "woow_paas_platform_lab"
MOUNT_BASE = "/opt/woow/addons"


def addon_names():
    return sorted(p.name for p in ADDONS_DIR.iterdir() if (p / "__manifest__.py").is_file())


def cm_name(addon, suffix=""):
    base = "woow-paas-platform-lab-addon" if addon == OVERLAY else "woow-paas-lab-addon-" + addon.replace("_", "-")
    return base + suffix


def vol_name(addon):
    return "lab-addon" if addon == OVERLAY else "lab-addon-" + addon.replace("_", "-")


def mount_path(addon):
    return f"{MOUNT_BASE}/{addon}"


def key_for(rel):
    return rel.replace("/", ".")


def files(addon):
    base = ADDONS_DIR / addon
    out = [(p.relative_to(base).as_posix(), p.read_bytes()) for p in sorted(base.rglob("*"))
           if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    keys = [key_for(rel) for rel, _ in out]
    assert len(keys) == len(set(keys)), f"{addon}: two files map to the same ConfigMap key"
    return out


def items(addon):
    return [{"key": key_for(rel), "path": rel} for rel, _ in files(addon)]


def configmap(addon, name, namespace=None, labels=None):
    data, binary = {}, {}
    for rel, raw in files(addon):
        try:
            data[key_for(rel)] = raw.decode("utf-8")
        except UnicodeDecodeError:
            binary[key_for(rel)] = base64.b64encode(raw).decode()
    meta = {"name": name, **({"namespace": namespace} if namespace else {}), "labels": dict(labels or {})}
    cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": meta, "data": data}
    if binary:
        cm["binaryData"] = binary
    return cm


def extra_modules():
    """lab-extra-modules.txt：每次 overlay 更新都 -i 的模組（# 後面是註解）。"""
    f = ROOT / "lab-extra-modules.txt"
    if not f.exists():
        return []
    return [ln.split("#", 1)[0].strip() for ln in f.read_text().splitlines() if ln.split("#", 1)[0].strip()]
