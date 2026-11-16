#!/usr/bin/env bash
# overlay addon 改完後的一鍵套用（2026-11-15 修正順序）：
#   ① 先用每個 addon 的「-next」ConfigMap 跑 odoo -i <lab-extra-modules.txt> -u woow_paas_platform_lab（web／cron 照跑，不動 helm）
#      addon 清單與 ConfigMap 規則在 tools/lab_addons.py（overlay＋addons/ 底下 vendored 的模組）
#   ② 再 helm upgrade 平台（post-renderer 重建正式 ConfigMap；若檔案清單變了 Deployment 會滾動）
# 順序不能反：chart 的 upgrade-gate 會比對「DB 裡的模組版本」與 manifest，manifest 比 DB 新就 exit（web 起不來）。
set -euo pipefail
cd "$(dirname "$0")/.."
CTX=${KUBE_CONTEXT:-default}; K=(kubectl --context "$CTX" -n paas-system)
python3 - <<'PYEOF' | "${K[@]}" apply -f -
import sys, yaml
sys.path.insert(0, "tools")
import lab_addons as L
docs = [L.configmap(a, L.cm_name(a, "-next"), "paas-system", {"woow.paas/lab-overlay": "next"}) for a in L.addon_names()]
print(yaml.safe_dump_all(docs, allow_unicode=True, sort_keys=False))
PYEOF
"${K[@]}" delete job lab-overlay-update --ignore-not-found --wait=true >/dev/null
python3 tools/with-lab-addon-items.py jobs/lab-overlay-update.yaml --configmap-suffix -next --install-extras | "${K[@]}" apply -f -
"${K[@]}" wait --for=condition=complete --timeout=20m job/lab-overlay-update || { "${K[@]}" logs job/lab-overlay-update --tail=40; exit 1; }
"${K[@]}" logs job/lab-overlay-update | grep -E 'woow_paas_platform_lab' | tail -8
helm --kube-context "$CTX" upgrade paas-odoo-platform oci://ghcr.io/woowtech/charts/woow-odoo --version 0.2.27 -n paas-system \
  -f values/woow-odoo.platform.lab.yaml -f values/secrets.platform.lab.yaml --post-renderer tools/post-render-lab-addon.py --wait --timeout 15m | grep -E '^(STATUS|REVISION)'
# RESTART=1（預設）建議留著，除非這次只改了 data XML：
#   - Python 改了：web／cron 要重啟才會載入新程式（檔案清單沒變時 Deployment 不會自己滾動）。
#   - static（OWL 模板／JS／CSS）改了：保守起見也重啟。① 的 -u 可能讓 web 先用舊檔算出 asset bundle 並快取（推測，未實證）。
#   ⚠ 驗證畫面時瀏覽器要真的重新整理：單頁 app 只改 # 後面的網址不會重新載入，會一直跑舊的 JS（2026-11-15 踩到）。
if [[ "${RESTART:-1}" == 1 ]]; then
  "${K[@]}" rollout restart deploy/paas-odoo-platform deploy/paas-odoo-platform-cron
  "${K[@]}" rollout status deploy/paas-odoo-platform --timeout=15m
  "${K[@]}" rollout status deploy/paas-odoo-platform-cron --timeout=15m
fi
"${K[@]}" delete configmap -l woow.paas/lab-overlay=next --ignore-not-found
