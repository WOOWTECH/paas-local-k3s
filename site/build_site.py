# woowtech Cloud 一頁式首頁：一次性建立（odoo shell 執行）。
#
# 用法（在平台 web pod 裡）：
#   kubectl --context default -n paas-system cp site/assets <web-pod>:/tmp/ww-site-assets -c odoo
#   kubectl --context default -n paas-system cp site/custom_rules.scss <web-pod>:/tmp/ww-site-assets/custom_rules.scss -c odoo
#   kubectl --context default -n paas-system exec -i <web-pod> -c odoo -- env WW_ASSETS=/tmp/ww-site-assets \
#       odoo shell -c /etc/odoo/odoo.conf -d woow_lab --no-http < site/build_site.py
#
# ⚠ 建好之後一律在「網站編輯器」裡改內容。首頁已經有內容時本腳本拒絕執行（避免蓋掉編輯），
#   要整頁重建才加 WW_FORCE=1。
#
# 全部用 Odoo 網站內建的 snippet（s_cover、s_text_image、s_cards_soft、s_key_benefits、s_numbers、
# s_features_grid、s_call_to_action）與主題設定（字型、配色、按鈕圓角），寫法跟編輯器存檔一樣：
# 首頁、頁首按鈕、頁尾都是「這個網站專屬的副本」（website-specific COW），之後 -u website 不會洗掉。
import base64
import os
import re

A = os.environ.get("WW_ASSETS", "/tmp/ww-site-assets")
FORCE = os.environ.get("WW_FORCE") == "1"
View = env["ir.ui.view"]
W = env["website"].browse(1)
WCTX = dict(website_id=W.id)


def read(name):
    with open(os.path.join(A, name), "rb") as fh:
        return fh.read()


home = View.search([("key", "=", "website.homepage"), ("website_id", "=", W.id)], limit=1)
if home and re.search(r'<div id="wrap"[^>]*?(?<!/)>\s*<(?!/)', home.arch_db or "") and not FORCE:
    print("SKIP: 首頁已經有內容（請改用網站編輯器；要整頁重建才加 WW_FORCE=1）")
    raise SystemExit(0)

# ---- 圖片：公開附件（編輯器的媒體庫看得到，可以換） ------------------------------------
Att = env["ir.attachment"]


def attach(name, mimetype):
    vals = {"name": name, "datas": base64.b64encode(read(name)), "mimetype": mimetype,
            "res_model": "ir.ui.view", "res_id": 0, "public": True}
    att = Att.search([("name", "=", name), ("res_model", "=", "ir.ui.view"), ("res_id", "=", 0)], limit=1)
    att = att.write(vals) and att if att else Att.create(vals)
    return att.image_src or "/web/image/%s" % att.id


URL = {
    "HERO": attach("bg-frosted-fluted.jpg", "image/jpeg"),
    "SHOT": attach("product-workspace.png", "image/png"),
    "LOGO": attach("logo-lockup-blue.svg", "image/svg+xml"),
}
for key, icon in (("IC_DB", "database-outline"), ("IC_AI", "robot-happy-outline"),
                  ("IC_MCP", "transit-connection-variant"), ("IC_HOME", "home-automation"),
                  ("IC_NET", "server-network"), ("IC_LOCK", "account-lock-outline"),
                  ("IC_KEEP", "backup-restore"), ("IC_SHIELD", "shield-check-outline")):
    URL[key] = attach("mdi-%s.svg" % icon, "image/svg+xml")

# ---- 網站基本設定 ----------------------------------------------------------------------
FONT_LINKS = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin=""/>\n'
              '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700'
              '&amp;family=Yellowtail&amp;display=swap"/>')
W.write({
    "name": "woowtech Cloud",
    "logo": base64.b64encode(read("logo-lockup-blue.svg")),
    "favicon": base64.b64encode(read("favicon.png")),
    "configurator_done": True,
    # Odoo 只會載入「有指定給字型欄位」的 Google 字型；中文 Noto Sans TC 與手寫字 Yellowtail 另外在 <head> 載入
    # （網站 → 設定 → 自訂程式碼，可在後台修改）
    "custom_code_head": FONT_LINKS,
})

# ---- 主題（等同編輯器「主題」分頁的設定）---------------------------------------------------
Assets = env["web_editor.assets"]
Assets.make_scss_customization("/website/static/src/scss/options/user_values.scss", {
    "font": "'Outfit'", "headings-font": "'Poppins'", "navbar-font": "'Poppins'", "buttons-font": "'Poppins'",
    "google-fonts": "('Outfit', 'Poppins', 'Noto Sans TC', 'Yellowtail')",
    "btn-border-radius": "999px", "btn-border-radius-sm": "999px", "btn-border-radius-lg": "999px",
    "btn-padding-y": ".6rem", "btn-padding-x": "1.4rem", "btn-padding-y-lg": ".8rem", "btn-padding-x-lg": "1.9rem",
    "input-border-radius": "12px", "input-border-radius-sm": "12px", "input-border-radius-lg": "12px",
    "headings-line-height": "1.15", "body-line-height": "1.65",
})
Assets.make_scss_customization("/website/static/src/scss/options/colors/user_color_palette.scss", {
    "o-color-1": "#6183FC",   # 主色：品牌藍（按鈕、連結）
    "o-color-2": "#EEF2FF",   # 次色：淡藍（第 3 種區塊底色）
    "o-color-3": "#EFF1F5",   # 淺色：品牌灰（第 2 種區塊底色）
    "o-color-4": "#FFFFFF",   # 白（第 1 種區塊底色）
    "o-color-5": "#212121",   # 深色：主要文字
    "o-cc1-text": "#646262", "o-cc1-headings": "#212121",
    "o-cc2-text": "#646262", "o-cc2-headings": "#212121",
    "o-cc3-text": "#646262", "o-cc3-headings": "#212121",
    "o-cc4-btn-primary": "#FFFFFF",
    "menu": 1, "footer": 2, "copyright": 2,
})
with open(os.path.join(A, "custom_rules.scss"), encoding="utf-8") as fh:
    Assets.save_asset("/website/static/src/scss/user_custom_rules.scss", "web.assets_frontend", fh.read(), "scss")


def card(icon, title, body, count):
    return f'''
      <div data-name="Card" class="col-lg-3 col-md-6 pt16 pb16">
        <div class="s_card card o_cc o_cc1 h-100" data-vxml="001" data-snippet="s_card" data-name="Card">
          <div class="card-body">
            <div class="ww-icon-tile mb-3"><img src="{URL[icon]}" class="img" alt=""/></div>
            <h3 class="h5-fs card-title">{title}</h3>
            <p class="card-text">{body}</p>
            <p class="ww-count">{count}</p>
          </div>
        </div>
      </div>'''


def feature(icon, title, body):
    return f'''
          <div class="col-md-6 py-3" data-name="Box">
            <span class="ww-icon-tile mb-3"><img src="{URL[icon]}" class="img" alt=""/></span>
            <h4 class="h5-fs">{title}</h4>
            <p>{body}</p>
          </div>'''


def step(n, title, body):
    return f'''
      <div class="col-lg-4 pt48 pb24">
        <span class="display-3-fs text-o-color-1">{n}</span>
        <div class="s_hr pt8 pb24" data-snippet="s_hr" data-name="Separator"><hr class="w-100 mx-auto"/></div>
        <h3 class="h4-fs">{title}</h3>
        <p>{body}</p>
      </div>'''


def number(value, label):
    return f'''
          <div class="col-lg-4 pt24 pb24 text-center" data-name="Number Box">
            <p class="lead"><span class="s_number display-1-fs">{value}</span><br/><span class="h5-fs">{label}</span></p>
          </div>'''


SECTIONS = f'''
<section class="s_cover o_cc o_cc1 oe_img_bg o_bg_img_center pt160 pb160" data-snippet="s_cover" data-name="Cover" style="background-image: url('{URL["HERO"]}');">
  <div class="container s_allow_columns">
    <div class="row">
      <div class="col-lg-8 offset-lg-2 ww-glass pt48 pb40 px-4 px-lg-5">
        <p class="ww-kicker" style="text-align: center;">woowtech Cloud · 企業雲端服務平台</p>
        <h1 class="display-4" style="text-align: center;">需要的服務，<br/>幾分鐘就開好</h1>
        <p class="lead" style="text-align: center;">woowtech Cloud 是公司內部的雲端服務平台，跑在我們自己的機器上。從 22 種服務範本挑一個，系統會替你準備好獨立的空間、裝好服務，再給你一個網址。</p>
        <p style="text-align: center;"><a href="/woow" class="btn btn-primary btn-lg mb-2">登入平台</a>&#160;<a href="#templates" class="btn btn-outline-primary btn-lg mb-2">看看有哪些服務</a></p>
        <p class="small mb-0" style="text-align: center;">使用公司帳號登入；還沒有帳號，請找系統管理員開通。</p>
      </div>
    </div>
  </div>
</section>

<section class="s_text_image o_cc o_cc1 pt96 pb96" data-snippet="s_text_image" data-name="Text - Image" id="intro" data-anchor="true">
  <div class="container">
    <div class="row align-items-center">
      <div class="col-lg-5 pt16 pb16">
        <p class="ww-script">Human-centered</p>
        <h2 class="h3-fs">一個工作區，放進團隊要用的所有服務</h2>
        <p>先建立一個工作區，再從範本開服務。每個工作區都是獨立的空間，有自己的資源上限和網路邊界，也可以邀請同事一起管理。</p>
        <ul class="ww-checklist">
          <li>資料庫、自動化、AI 工具、MCP、VPN 範本都準備好了</li>
          <li>需要對外的服務，會自動拿到 https 網址</li>
          <li>不用時直接刪除，資源自動收回</li>
        </ul>
      </div>
      <div class="col-lg-6 offset-lg-1 pt16 pb16">
        <img src="{URL["SHOT"]}" class="img img-fluid mx-auto rounded ww-float" alt="woowtech Cloud 工作區畫面：資源配額與執行中的服務"/>
      </div>
    </div>
  </div>
</section>

<section class="s_cards_soft o_cc o_cc2 pt96 pb80" data-snippet="s_cards_soft" data-name="Cards Soft" id="templates" data-anchor="true">
  <div class="container">
    <div class="row s_nb_column_fixed">
      <div class="col-lg-12 pb24">
        <p class="ww-kicker" style="text-align: center;">Templates</p>
        <h2 style="text-align: center;">22 種服務範本，挑了就開</h2>
        <p class="lead" style="text-align: center;">常用的資料庫、自動化工具、AI 助手和 MCP 伺服器都已經準備好。</p>
      </div>{card("IC_DB", "資料庫與基本服務", "PostgreSQL、Redis、Odoo、n8n、LiteLLM、EMQX、Nextcloud", "7 種範本")}{card("IC_AI", "AI 與開發工具", "Pi agent、Hermes、Open Design、Omnigent、Code Server", "5 種範本")}{card("IC_MCP", "MCP 伺服器", "讓 AI 助手連上 Odoo、n8n、Hermes、LiteLLM、Headscale、EMQX、Nextcloud", "7 種範本")}{card("IC_HOME", "VPN 與智慧家庭", "Headscale、Tailscale、Home Assistant 完整版", "3 種範本")}
    </div>
  </div>
</section>

<section class="s_key_benefits o_cc o_cc1 pt96 pb64" data-snippet="s_key_benefits" data-name="Key benefits" id="start" data-anchor="true">
  <div class="container">
    <div class="row s_nb_column_fixed">
      <div class="col-lg-12">
        <p class="ww-kicker">How it works</p>
        <h2>三個步驟，開始用 woowtech Cloud</h2>
      </div>{step(1, "登入平台", "用公司帳號登入。還沒有帳號的話，請找系統管理員開通。")}{step(2, "建立工作區", "替專案或團隊建一個工作區，也可以邀請同事一起管理。")}{step(3, "從範本開服務", "選好範本按開通，幾分鐘後就有能用的服務和網址。")}
    </div>
  </div>
</section>

<section class="s_numbers o_cc o_cc3 pt80 pb80" data-snippet="s_numbers" data-name="Numbers">
  <div class="container">
    <div class="row s_nb_column_fixed">
      <div class="col-lg-4">
        <p class="ww-kicker">At a glance</p>
        <h3 class="mb-3 h4">開服務不用等人</h3>
        <p class="lead">這些是我們在測試環境實際量到的數字。</p>
      </div>
      <div class="col-lg-7 offset-lg-1">
        <div class="row">{number("22", "種服務範本")}{number("2–12", "分鐘開好一個服務")}{number("7", "天後才清除刪掉的資料")}
        </div>
      </div>
    </div>
  </div>
</section>

<section class="s_features_grid o_cc o_cc1 pt96 pb80" data-snippet="s_features_grid" data-name="Features Grid" data-vcss="001" id="security" data-anchor="true">
  <div class="container">
    <div class="row">
      <div class="col-lg-5 s_col_no_bgcolor pb24">
        <p class="ww-kicker">Security</p>
        <h2 class="h3-fs">放心把服務放上來</h2>
        <p class="lead">每個工作區都有自己的邊界，刪掉的服務也不會馬上消失。</p>
      </div>
      <div class="col-lg-7 s_col_no_bgcolor pb24">
        <div class="row">{feature("IC_NET", "工作區彼此隔離", "每個工作區有自己的資源上限，網路預設互不相通，只看得到自己的服務。")}{feature("IC_LOCK", "服務都要登入", "對外網址經過 Cloudflare，服務本身也要登入才能使用。")}{feature("IC_KEEP", "刪掉不會馬上消失", "刪除服務後，資料會先保留 7 天才真正清除。")}{feature("IC_SHIELD", "平台每天備份", "平台本身的資料每天自動備份。")}
        </div>
      </div>
    </div>
  </div>
</section>

<section class="s_call_to_action o_cc o_cc4 pt72 pb72" data-snippet="s_call_to_action" data-name="Call to Action">
  <div class="container">
    <div class="row align-items-center">
      <div class="col-lg-9">
        <h3 class="h2-fs">開你的第一個服務</h3>
        <p class="lead mb-0">用公司帳號登入 woowtech Cloud；需要帳號或遇到問題，請找系統管理員。</p>
      </div>
      <div class="col-lg-3 pt24 pt-lg-0">
        <p style="text-align: right;"><a href="/woow" class="btn btn-primary btn-lg">登入平台</a></p>
      </div>
    </div>
  </div>
</section>
'''

HOME_ARCH = f'''<t name="Homepage" t-name="website.homepage">
    <t t-call="website.layout">
        <t t-set="pageName" t-value="'homepage'"/>
        <div id="wrap" class="oe_structure">{SECTIONS}
        </div>
    </t>
</t>'''

FOOTER_INNER = f'''<div id="footer" class="oe_structure oe_structure_solo" t-ignore="true" t-if="not no_footer">
            <section class="s_text_block pt56 pb32" data-snippet="s_text_block" data-name="Text">
                <div class="container">
                    <div class="row">
                        <div class="col-lg-5 pt16 pb16">
                            <p><img src="{URL["LOGO"]}" class="img" style="height: 32px; width: auto;" alt="woowtech"/></p>
                            <p>woowtech Cloud 是渥屋科技的企業內部雲端服務平台：挑範本、開服務、拿網址，一個工作區管好團隊要用的服務。</p>
                        </div>
                        <div class="col-lg-3 offset-lg-1 pt16 pb16">
                            <h5 class="mb-3">快速連結</h5>
                            <ul class="list-unstyled">
                                <li><a href="/woow">登入平台</a></li>
                                <li><a href="/#templates">服務範本</a></li>
                                <li><a href="/#start">怎麼開始</a></li>
                                <li><a href="/odoo">管理後台</a></li>
                            </ul>
                        </div>
                        <div class="col-lg-3 pt16 pb16">
                            <h5 class="mb-3">需要協助</h5>
                            <p>帳號開通、權限或服務有問題，請找系統管理員。</p>
                            <p class="ww-kicker mb-0">The Smart Space Solution</p>
                        </div>
                    </div>
                </div>
            </section>
        </div>'''


def write_both_langs(view, arch):
    """原文（en_US）與網站語言（zh_TW）寫同一份，編輯器以哪個語言開都一致。"""
    view.with_context(lang="en_US", **WCTX).write({"arch_db": arch})
    specific = View.with_context(active_test=False).search([("key", "=", view.key), ("website_id", "=", W.id)], limit=1)
    specific.with_context(lang="zh_TW", **WCTX).write({"arch_db": arch})
    return specific


# ---- 首頁 --------------------------------------------------------------------------------
home = write_both_langs(home or View.search([("key", "=", "website.homepage"), ("website_id", "=", False)], limit=1), HOME_ARCH)

# ---- 頁首按鈕：「聯絡我們」→「登入平台」(/woow) ---------------------------------------------
cta_src = View.with_context(**WCTX).search([("key", "=", "website.header_call_to_action")]).filter_duplicate()
cta_arch = re.sub(r'href="[^"]*"', 'href="/woow"', cta_src.with_context(lang="en_US").arch_db, count=1)
cta_arch = re.sub(r'(btn_cta">)[^<]*(</a>)', r"\1登入平台\2", cta_arch)
write_both_langs(cta_src, cta_arch)

# ---- 頁尾 ----------------------------------------------------------------------------------
foot_src = View.with_context(**WCTX).search([("key", "=", "website.footer_custom")]).filter_duplicate()
foot_arch = re.sub(r'<div id="footer".*</div>\s*(?=</xpath>)', FOOTER_INNER + "\n    ", foot_src.with_context(lang="en_US").arch_db, flags=re.S)
write_both_langs(foot_src, foot_arch)
copy_src = View.with_context(**WCTX).search([("key", "=", "website.footer_copyright_company_name")]).filter_duplicate()
copy_arch = re.sub(r'(o_footer_copyright_name me-2">)[^<]*(</span>)', r"\1Copyright © WOOW Technology Co., Ltd.\2",
                   copy_src.with_context(lang="en_US").arch_db)
write_both_langs(copy_src, copy_arch)

# ---- 頁首不要的元素（等同編輯器頁首選項關掉）：登入連結（已有「登入平台」按鈕）、示範電話、搜尋 -------
for key in ("portal.user_sign_in", "website.header_text_element", "website.header_search_box"):
    View.with_context(active_test=False, **WCTX).search([("key", "=", key)]).filter_duplicate() \
        .filtered("active").write({"active": False})

# ---- 選單：一頁式的段落錨點 ---------------------------------------------------------------------
top = W.menu_id
top.child_id.unlink()
for seq, (name, url) in enumerate((("系統介紹", "/#intro"), ("服務範本", "/#templates"),
                                    ("怎麼開始", "/#start"), ("安全與資料", "/#security")), start=1):
    env["website.menu"].create({"name": name, "url": url, "parent_id": top.id, "website_id": W.id, "sequence": seq * 10})

# ---- 搜尋引擎與分享用的標題、描述 ------------------------------------------------------------
for page in env["website.page"].search([("url", "=", "/"), ("website_id", "in", (W.id, False))]):
    page.with_context(**WCTX).write({
        "website_meta_title": "woowtech Cloud｜企業雲端服務平台",
        "website_meta_description": "公司內部的雲端服務平台：從 22 種服務範本挑一個，幾分鐘就拿到可以用的服務與網址。",
    })

env.registry.clear_cache("assets")
env.registry.clear_cache("templates")
env.registry.clear_cache()
env.cr.commit()
env.registry.signal_changes()
print("DONE homepage view", home.id, "| menu items", [m.name for m in W.menu_id.child_id], "| assets:", sorted(URL))
