{
    "name": "woowtech Cloud 存取控制",
    "version": "18.0.1.0.0",
    "category": "WOOW",
    "summary": "讓 Woow Website Auth 的規則也管到 /woow 平台與平台 API（本機複本）",
    "author": "Woow",
    "license": "OPL-1",
    # 使用者 2026-11-16：用 woowtech 自製的 web auth 管理、限制可以用 woowtech Cloud 的人，網站和平台都管。
    # 獨立成一個小模組（不放進 woow_paas_platform_lab）：日後有人在 Apps 解除安裝 web auth，
    # 只會連帶移除這個轉接模組，不會把本機差異層一起拆掉。
    "depends": ["woow_paas_platform", "woow_website_auth"],
    "data": [
        "data/groups.xml",
        "data/rules.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "auto_install": False,
}
