#!/usr/bin/env bash
# 在本機叢集的筆電節點跑一個 skopeo Job，把 tools/images.txt 的映像從 JCR（經 tailnet）原樣複製到 GHCR。
# 需要：~/woow_tech_credential/jcr-readonly.env（JCR_USER/JCR_PASS）、~/woow_tech_credential/ghcr-pat.env（GHCR_PAT）
set -euo pipefail
KUBE_CONTEXT=${KUBE_CONTEXT:-default}; NS=paas-local-infra; TAILNET_IP=${TAILNET_IP:-100.93.200.36}
# shellcheck disable=SC1090
source ~/woow_tech_credential/jcr-readonly.env; source ~/woow_tech_credential/ghcr-pat.env
: "${JCR_USER:?}" "${JCR_PASS:?}" "${GHCR_PAT:?}"
K=(kubectl --context "$KUBE_CONTEXT")
"${K[@]}" create ns "$NS" --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null
"${K[@]}" -n "$NS" create secret generic mirror-creds --from-literal=src="${JCR_USER}:${JCR_PASS}" --from-literal=dst="WOOWTECH:${GHCR_PAT}" --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null
"${K[@]}" -n "$NS" create configmap mirror-images --from-file=images.txt="$(dirname "$0")/images.txt" --dry-run=client -o yaml | "${K[@]}" apply -f - >/dev/null
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
              grep -v '^#' /work/images.txt | grep -v '^\s*$' | while read -r src dst; do
                echo "== \$src -> \$dst"
                skopeo copy --preserve-digests --retry-times 3 \
                  --src-creds "\$(cat /creds/src)" --dest-creds "\$(cat /creds/dst)" \
                  "docker://\$src" "docker://\$dst"
                skopeo inspect --creds "\$(cat /creds/dst)" "docker://\$dst" --format '{{.Digest}}' | sed "s/^/   dest digest: /"
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
