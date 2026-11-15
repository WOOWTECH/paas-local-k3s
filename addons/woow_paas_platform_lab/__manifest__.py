{
    "name": "Woow PaaS Platform - Lab overlay",
    "version": "18.0.1.0.4",
    "category": "WOOW",
    "summary": "本機 k3s 複本的差異層：隱藏 Security Access／Home Connect、範本改指 ghcr.io、local-path",
    "author": "Woow",
    "license": "OPL-1",
    "depends": ["woow_paas_platform"],
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
