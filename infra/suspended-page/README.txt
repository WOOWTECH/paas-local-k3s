# 停權說明頁（照 paas-app-bundle-cd/paas-suspended-page-stg，只改續訂連結＝本機平台、replicas 1）
# operator 在服務欠費停權時把該服務的 tunnel 路由改指 http://paas-suspended-page.paas-stg-cloudflare-system.svc.cluster.local:8080
# 套用：kubectl --context default apply -f infra/suspended-page/
