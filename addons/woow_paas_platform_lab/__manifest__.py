{
    "name": "Woow PaaS Platform - Lab overlay",
    "version": "18.0.1.0.12",
    "category": "WOOW",
    "summary": "本機 k3s 複本的差異層：隱藏 Security Access／Home Connect、範本改指 ghcr.io、local-path",
    "author": "Woow",
    "license": "OPL-1",
    "depends": [
        "woow_paas_platform",
        # 使用者 2026-11-16：本機平台首頁放 woowtech Cloud 一頁式介紹（Odoo 網站模組＋內建 snippet，可在編輯器調整）。
        # 正式站平台本來就有裝 website；加在這裡讓重建平台時（platform-init -i woow_paas_platform_lab）也會一起裝。
        "website",
    ],
    # 上游 seed 全是 noupdate=0，每次 -u 都會洗回預設；本模組排在上游之後載入，
    # 所以這裡的 record 與 <function> 每次 -u 都會再套一次，差異層才站得住。
    "data": [
        "data/lab_redis_plan.xml",
        "data/lab_overrides.xml",
    ],
    "assets": {
        "woow_paas_platform.assets_paas": [
            "woow_paas_platform_lab/static/src/paas/workspace_hide_sections.xml",
        ],
    },
    "installable": True,
    "auto_install": False,
}
