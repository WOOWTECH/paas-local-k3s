# 目錄清單指紋（加 --content 連每個檔案內容的 sha256 一起算，資料小時用）：每個項目的型別／權限／擁有者／大小／修改時間（整數秒）／連結目標，排序後 sha256（socket 不算，tar 本來就不收）
import hashlib, os, stat, sys
root = sys.argv[1]
content = "--content" in sys.argv[2:]

def digest(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

rows, total = [], 0
st = os.lstat(root); rows.append(f"root {st.st_mode:o} {st.st_uid} {st.st_gid}")
for dp, dns, fns in os.walk(root):
    for name in dns + fns:
        p = os.path.join(dp, name); st = os.lstat(p); rel = os.path.relpath(p, root)
        if stat.S_ISREG(st.st_mode):
            rows.append(f"f {st.st_mode:o} {st.st_uid} {st.st_gid} {st.st_size} {int(st.st_mtime)} {digest(p) if content else '-'} {rel}"); total += st.st_size
        elif stat.S_ISDIR(st.st_mode):
            rows.append(f"d {st.st_mode:o} {st.st_uid} {st.st_gid} {rel}")
        elif stat.S_ISLNK(st.st_mode):
            rows.append(f"l {st.st_uid} {st.st_gid} {os.readlink(p)} {rel}")
        elif not stat.S_ISSOCK(st.st_mode):
            rows.append(f"o {st.st_mode:o} {rel}")
h = hashlib.sha256()
for r in sorted(rows):
    h.update(r.encode("utf-8", "surrogateescape") + b"\n")
print(f"manifest {h.hexdigest()} entries {len(rows)} bytes {total}")
