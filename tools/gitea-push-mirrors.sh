#!/usr/bin/env bash
# 在 Gitea 上為 6 個 repo 建立 push mirror → GitHub（private）。需要：
#   ~/.config/tea/config.yml 的 Gitea token（toypark1234，對這些 repo 有 admin）
#   GitHub 寫入權：預設取 `gh auth token`；或 ~/woow_tech_credential/github-mirror-pat.env：GITHUB_MIRROR_PAT=…（fine-grained，Contents RW）
# Gitea 公開網址被 Cloudflare Access 擋 → 用 --resolve 直打 woow-k3s 節點 tailnet IP（憑證是正式 LE，可驗）。
set -euo pipefail
GITEA_HOST=git-prod.woowtech.io; TAILNET_IP=${TAILNET_IP:-100.93.200.36}
GITEA_TOKEN=$(grep -E "^\s*token:" ~/.config/tea/config.yml | head -1 | awk '{print $2}' | tr -d '"'"'")
# 2026-11-15 使用者決定：直接用這台機器 gh CLI 已登入的 token（repo scope）；若日後改用小鑰匙，放 github-mirror-pat.env 即優先採用
if [[ -f ~/woow_tech_credential/github-mirror-pat.env ]]; then
  # shellcheck disable=SC1090
  source ~/woow_tech_credential/github-mirror-pat.env
fi
GITHUB_MIRROR_PAT=${GITHUB_MIRROR_PAT:-$(gh auth token)}
: "${GITHUB_MIRROR_PAT:?GITHUB_MIRROR_PAT missing}"
API="https://${GITEA_HOST}/api/v1"; CURL=(curl -sS -m 30 --resolve "${GITEA_HOST}:443:${TAILNET_IP}" -H "Authorization: token ${GITEA_TOKEN}" -H "Content-Type: application/json")
# gitea_owner/repo  github_repo
PAIRS=(
  "odoo-addons/woow_paas_platform odoo-addon-woow-paas-platform"
  "woow-paas/woow-paas-charts woow-paas-charts"
  "woow-paas/paas-odoo-ci paas-odoo-ci"
  "woow-paas/paas-app-bundle-cd paas-app-bundle-cd"
  "cc/woowprd woowprd"
  "woow-paas/woow-machines-operator woow-machines-operator"
)
for pair in "${PAIRS[@]}"; do
  set -- $pair; src=$1; dst=$2
  existing=$("${CURL[@]}" "${API}/repos/${src}/push_mirrors" | python3 -c 'import sys,json; print(" ".join(m.get("remote_address","") for m in json.load(sys.stdin)))')
  if [[ "$existing" == *"github.com/WOOWTECH/${dst}"* ]]; then echo "exists: ${src} → ${dst}"; continue; fi
  body=$(python3 - "$dst" "$GITHUB_MIRROR_PAT" <<'PY'
import json,sys
print(json.dumps({"remote_address": f"https://github.com/WOOWTECH/{sys.argv[1]}.git",
  "remote_username": "WOOWTECH", "remote_password": sys.argv[2],
  "interval": "8h0m0s", "sync_on_commit": True}))
PY
)
  "${CURL[@]}" -X POST "${API}/repos/${src}/push_mirrors" -d "$body" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("created:", d.get("remote_name"), d.get("remote_address"), "interval", d.get("interval"))'
  # 立刻同步一次
  "${CURL[@]}" -X POST "${API}/repos/${src}/push_mirrors-sync" -o /dev/null -w "sync requested: ${src} http=%{http_code}\n"
done
echo "稍後查狀態：GET /repos/<owner>/<repo>/push_mirrors 看 last_update／last_error"
