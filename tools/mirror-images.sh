#!/usr/bin/env bash
# 在本機叢集的筆電節點跑一個 skopeo Job，把映像清單（預設 tools/images.txt；可傳第一個參數換清單）從 JCR（經 tailnet）原樣複製到 GHCR。
# 需要：~/woow_tech_credential/jcr-readonly.env（JCR_USER/JCR_PASS）、~/woow_tech_credential/ghcr-pat.env（GHCR_PAT）
set -euo pipefail
KUBE_CONTEXT=${KUBE_CONTEXT:-default}; NS=paas-local-infra; TAILNET_IP=${TAILNET_IP:-100.93.200.36}
# shellcheck disable=SC1090
source ~/woow_tech_credential/jcr-readonly.env
[[ -f ~/woow_tech_credential/ghcr-pat.env ]] && source ~/woow_tech_credential/ghcr-pat.env
GHCR_PAT=${GHCR_PAT:-$(gh auth token)}  # 2026-11-15：預設用 gh CLI 的 token（write:packages）
: "${JCR_USER:?}" "${JCR_PASS:?}" "${GHCR_PAT:?}"
K=(kubectl --context "$KUBE_CONTEXT")
"${K[@]}" create ns "$NS" --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null
"${K[@]}" -n "$NS" create secret generic mirror-creds --from-literal=src="${JCR_USER}:${JCR_PASS}" --from-literal=dst="WOOWTECH:${GHCR_PAT}" --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null
LIST=${1:-$(dirname "$0")/images.txt}
"${K[@]}" -n "$NS" create configmap mirror-images --from-file=images.txt="$LIST" --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null
"${K[@]}" -n "$NS" delete job image-mirror --ignore-not-found >/dev/null
cat <<YAML | "${K[@]}" apply -f -
apiVersion: batch/v1
kind: Job
metadata: { name: image-mirror, namespace: ${NS} }
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      nodeSelector: { kubernetes.io/hostname: woowtechcluster1-aorus-15p-xd }
      hostAliases:
        - ip: "${TAILNET_IP}"
          hostnames: ["jcr-prod.woowtech.io"]
      containers:
        - name: skopeo
          image: quay.io/skopeo/stable:v1.17.0
          command: ["/bin/bash", "-c"]
          args:
            - |
              set -euo pipefail
              # images.txt 的來源寫成 repo:tag@sha256:… 方便人看；skopeo 不接受 tag+digest 並存，所以拆成 repo@digest 來拉
              grep -v '^#' /work/images.txt | grep -v '^\s*$' | while read -r src dst; do
                digest="\${src#*@}"; repo_tag="\${src%%@*}"; repo="\${repo_tag%%:*}"
                echo "== \$repo@\$digest -> \$dst"
                skopeo copy --preserve-digests --multi-arch all --retry-times 3 \
                  --src-creds "\$(cat /creds/src)" --dest-creds "\$(cat /creds/dst)" \
                  "docker://\$repo@\$digest" "docker://\$dst"
                got="\$(skopeo inspect --creds "\$(cat /creds/dst)" --format '{{.Digest}}' "docker://\$dst")"
                if [[ "\$got" == "\$digest" ]]; then echo "   OK dest digest \$got"; else echo "   DIGEST MISMATCH expected \$digest got \$got"; exit 1; fi
              done
          volumeMounts:
            - { name: creds, mountPath: /creds, readOnly: true }
            - { name: images, mountPath: /work, readOnly: true }
      volumes:
        - name: creds
          secret: { secretName: mirror-creds }
        - name: images
          configMap: { name: mirror-images }
YAML
echo "follow: kubectl --context $KUBE_CONTEXT -n $NS logs -f job/image-mirror"
