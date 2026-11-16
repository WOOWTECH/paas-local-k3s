def post_init_hook(env):
    """安裝時把現有的帳號都加進「woowtech Cloud 使用者」（使用者決定：現有帳號先全部加入，之後由管理員增減）。"""
    group = env.ref("woow_paas_lab_access.group_cloud_user")
    skip = {"__system__", "default", "public", "portaltemplate"}
    users = env["res.users"].search([("active", "=", True)]).filtered(
        lambda u: u.login not in skip and not u._is_public())
    group.write({"users": [(4, u.id) for u in users]})
