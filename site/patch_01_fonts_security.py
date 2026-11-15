# 2026-11-16 第一次修正（已建好的網站直接改，不重跑 build_site.py）：
# 載入 Noto Sans TC／Yellowtail、「安全」區塊改成左標題＋右 2x2、頁首拿掉搜尋。之後一律用網站編輯器改。
import os, re, base64
View = env["ir.ui.view"]; W = env["website"].browse(1); WCTX = dict(website_id=W.id)
ns = {}
src = open(os.environ["WW_BUILD"], encoding="utf-8").read()
# 從 build_site.py 取出同一份 FONT_LINKS 與新的 security 區塊（feature() 需要圖示網址：沿用已上傳的附件）
Att = env["ir.attachment"]
URL = {}
for key, icon in (("IC_NET", "server-network"), ("IC_LOCK", "account-lock-outline"),
                  ("IC_KEEP", "backup-restore"), ("IC_SHIELD", "shield-check-outline")):
    a = Att.search([("name", "=", "mdi-%s.svg" % icon), ("res_model", "=", "ir.ui.view"), ("res_id", "=", 0)], limit=1)
    URL[key] = a.image_src
exec(src[src.index("def feature(icon, title, body):"):src.index("def step(n, title, body):")], {"URL": URL}, ns)
feature = ns["feature"]
sec_tpl = src[src.index('<section class="s_features_grid'):src.index('</section>', src.index('<section class="s_features_grid')) + len('</section>')]
new_sec = eval("f'''" + sec_tpl + "'''", {"feature": feature})
font_links = re.search(r"FONT_LINKS = \((.*?)\)\n", src, re.S).group(1)
font_links = eval("(" + font_links + ")")
W.write({"custom_code_head": font_links})
home = View.search([("key", "=", "website.homepage"), ("website_id", "=", W.id)], limit=1)
for lang in ("en_US", "zh_TW"):
    arch = home.with_context(lang=lang).arch_db
    arch2, n = re.subn(r'<section class="s_features_grid.*?</section>', new_sec.replace("\\", "\\\\"), arch, count=1, flags=re.S)
    assert n == 1, "security section not found (%s)" % lang
    home.with_context(lang=lang, **WCTX).write({"arch_db": arch2})
View.with_context(active_test=False, **WCTX).search([("key", "=", "website.header_search_box")]).filter_duplicate() \
    .filtered("active").write({"active": False})
env.registry.clear_cache("templates"); env.registry.clear_cache()
env.cr.commit(); env.registry.signal_changes()
print("PATCHED fonts + security section + header search")
