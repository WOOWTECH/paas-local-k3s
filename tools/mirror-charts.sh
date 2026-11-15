#!/usr/bin/env bash
# 從 Gitea Helm registry（經 tailnet）拉 chart，推到 oci://ghcr.io/woowtech/charts。需要 ~/woow_tech_credential/ghcr-pat.env。
set -euo pipefail
GITEA_HOST=git-prod.woowtech.io; TAILNET_IP=${TAILNET_IP:-100.93.200.36}
GITEA_TOKEN=$(grep -E "^\s*token:" ~/.config/tea/config.yml | head -1 | awk '{print $2}' | tr -d '"'"'")
# shellcheck disable=SC1090
[[ -f ~/woow_tech_credential/ghcr-pat.env ]] && source ~/woow_tech_credential/ghcr-pat.env
GHCR_PAT=${GHCR_PAT:-$(gh auth token)}; : "${GHCR_PAT:?}"  # 2026-11-15：預設用 gh CLI 的 token（write:packages）
# 第三欄＝目的地（預設 oci://ghcr.io/woowtech/charts）。omnigent 改放 paas-charts：GHCR 上 charts/omnigent 是別的專案的公開 package，推進去會變公開。
CHARTS=("woow-odoo 0.2.27" "woow-odoo 0.2.26" "paas-operator 0.1.36" "litellm 0.3.16" "emqx 0.1.11"
        "pi-agent 0.1.20" "hermes-agent 0.4.9" "open-design 0.5.10" "omnigent 0.1.19 oci://ghcr.io/woowtech/paas-charts")
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
printf '%s' "$GHCR_PAT" | helm registry login ghcr.io -u WOOWTECH --password-stdin
for c in "${CHARTS[@]}"; do set -- $c; name=$1; ver=$2; dest=${3:-oci://ghcr.io/woowtech/charts}
  curl -sS -m 60 --resolve "${GITEA_HOST}:443:${TAILNET_IP}" -H "Authorization: token ${GITEA_TOKEN}" \
    -o "$W/${name}-${ver}.tgz" "https://${GITEA_HOST}/api/packages/woow-paas/helm/${name}-${ver}.tgz"
  helm show chart "$W/${name}-${ver}.tgz" | grep -E '^(name|version):'
  # hermes-agent：Chart.yaml 說明含大量中文，helm push 的 manifest annotation 會被 GHCR 回 500 → 改用不帶說明的推法（tgz 原封不動）
  helm push "$W/${name}-${ver}.tgz" "$dest" || GHCR_TOKEN="$GHCR_PAT" python3 "$(dirname "$0")/oci-push-chart-nodesc.py" "$W/${name}-${ver}.tgz" "$dest"
done
