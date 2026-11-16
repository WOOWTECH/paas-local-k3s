# 2026-11-16 第二次修正（裝了課程與線上客服之後跑一次；之後一律在網站編輯器／設定裡改）：
# - 線上客服：使用者決定網站（首頁、登入頁）不顯示聊天按鈕 → 網站的即時聊天頻道清空（＝網站設定裡的「線上客服頻道」留空）
# - 課程：使用者決定放進首頁上方選單 →「安全與資料」後面加「課程」連到 /slides（website_slides 自己建的那筆就沿用、改名排序）
W = env["website"].browse(1)
WCTX = dict(website_id=W.id)
if "channel_id" in W._fields and W.channel_id:
    W.write({"channel_id": False})
Menu = env["website.menu"].with_context(**WCTX)
top = W.menu_id
slides = Menu.search([("website_id", "=", W.id), ("url", "in", ("/slides", "/slides/all"))], order="id")
siblings = top.child_id - slides
seq = max(siblings.mapped("sequence") or [0]) + 10
if slides:
    keep, extra = slides[0], slides[1:]
    extra.unlink()
    keep.write({"parent_id": top.id, "sequence": seq, "url": "/slides"})
else:
    keep = Menu.create({"name": "課程", "url": "/slides", "parent_id": top.id, "website_id": W.id, "sequence": seq})
for lang in ("en_US", "zh_TW"):
    keep.with_context(lang=lang).write({"name": "課程"})
env.registry.clear_cache("templates"); env.registry.clear_cache()
env.cr.commit(); env.registry.signal_changes()
print("PATCHED livechat channel:", W.channel_id.display_name if "channel_id" in W._fields else "n/a",
      "| top menu:", [(m.name, m.url) for m in top.child_id.sorted("sequence")])
