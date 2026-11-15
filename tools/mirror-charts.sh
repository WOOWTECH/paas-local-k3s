#!/usr/bin/env bash
# 從 Gitea Helm registry（經 tailnet）拉 chart，推到 oci://ghcr.io/woowtech/charts。需要 ~/woow_tech_credential/ghcr-pat.env。
set -euo pipefail
GITEA_HOST=git-prod.woowtech.io; TAILNET_IP=${TAILNET_IP:-100.93.200.36}
GITEA_TOKEN=$(grep -E "^\s*token:" ~/.config/tea/config.yml | head -1 | awk '{print $2}' | tr -d '"'"'")
# shellcheck disable=SC1090
source ~/woow_tech_credential/ghcr-pat.env; : "${GHCR_PAT:?}"
CHARTS=("woow-odoo 0.2.27" "woow-odoo 0.2.26" "paas-operator 0.1.36" "litellm 0.3.16" "emqx 0.1.11")
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
printf '%s' "$GHCR_PAT" | helm registry login ghcr.io -u WOOWTECH --password-stdin
for c in "${CHARTS[@]}"; do set -- $c; name=$1; ver=$2
  curl -sS -m 60 --resolve "${GITEA_HOST}:443:${TAILNET_IP}" -H "Authorization: token ${GITEA_TOKEN}" \
    -o "$W/${name}-${ver}.tgz" "https://${GITEA_HOST}/api/packages/woow-paas/helm/${name}-${ver}.tgz"
  helm show chart "$W/${name}-${ver}.tgz" | grep -E '^(name|version):'
  helm push "$W/${name}-${ver}.tgz" oci://ghcr.io/woowtech/charts
done
