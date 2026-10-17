"""لوحة تحكم الويب للبوت (تشتغل داخل نفس خدمة Render)."""
import collections
import datetime
import hashlib
import hmac
import time

import discord
from aiohttp import web

SESSION_TTL = 12 * 3600
COOKIE = "dash_session"
AUDIT = collections.deque(maxlen=100)
FAILS: dict[str, list[float]] = {}

SEC_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "img-src 'self' https://cdn.discordapp.com data:; frame-ancestors 'none'"
    ),
}


class ApiError(Exception):
    def __init__(self, msg: str, status: int = 400):
        self.msg, self.status = msg, status


def to_int(v, label="المعرّف") -> int:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        raise ApiError(f"{label} غير صالح")


def audit(action: str, detail: str):
    AUDIT.appendleft({"t": int(time.time()), "action": action, "detail": detail[:200]})


def role_is_safe(r: discord.Role) -> bool:
    p = r.permissions
    return not (r.is_default() or r.managed or p.administrator or p.manage_guild or p.manage_roles)


def register(app: web.Application, bot, deps: dict, token: str, password: str):
    if len(password) < 10:
        print("⚠️ DASHBOARD_PASSWORD قصيرة (لازم 10 حروف على الأقل). لوحة التحكم ما اتفتحتش.")
        return
    key = hashlib.sha256(f"{token}:{password}".encode()).digest()

    def sign(ts: str) -> str:
        return hmac.new(key, ts.encode(), hashlib.sha256).hexdigest()

    def valid_cookie(val) -> bool:
        if not val or "." not in val:
            return False
        ts, sig = val.split(".", 1)
        if not ts.isdigit() or not hmac.compare_digest(sig, sign(ts)):
            return False
        return time.time() - int(ts) < SESSION_TTL

    def client_ip(request) -> str:
        fwd = request.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or request.remote or "?"

    def get_guild(request) -> discord.Guild:
        g = bot.get_guild(to_int(request.match_info["gid"], "السيرفر"))
        if g is None:
            raise ApiError("السيرفر مش موجود", 404)
        return g

    async def body(request) -> dict:
        try:
            data = await request.json()
        except Exception:
            raise ApiError("بيانات غير صالحة")
        if not isinstance(data, dict):
            raise ApiError("بيانات غير صالحة")
        return data

    def text_channel(g: discord.Guild, cid) -> discord.TextChannel:
        ch = g.get_channel(to_int(cid, "الروم"))
        if not isinstance(ch, discord.TextChannel):
            raise ApiError("اختار روم نصي صالح")
        return ch

    def parse_color(v) -> int:
        try:
            return int(str(v).lstrip("#"), 16)
        except ValueError:
            return 0x5865F2

    async def log_to_discord(g: discord.Guild, title: str, desc: str):
        fn = deps.get("send_log")
        if fn:
            await fn(g, discord.Embed(title=f"🛠️ {title}", description=desc, color=discord.Color.blurple()))

    # ---------------- middleware ----------------
    @web.middleware
    async def mw(request, handler):
        try:
            if request.path.startswith("/api/") and request.path != "/api/login":
                if not valid_cookie(request.cookies.get(COOKIE)):
                    raise ApiError("غير مسجّل دخول", 401)
                if request.method != "GET" and request.content_type != "application/json":
                    raise ApiError("نوع الطلب غير صالح", 415)
            return await handler(request)
        except ApiError as e:
            return web.json_response({"error": e.msg}, status=e.status)
        except discord.Forbidden:
            return web.json_response({"error": "البوت ما عندوش صلاحية لهذا الإجراء"}, status=403)
        except discord.HTTPException as e:
            return web.json_response({"error": f"ديسكورد رفض الطلب: {e.text or e.status}"[:200]}, status=400)

    app.middlewares.append(mw)

    # ---------------- auth ----------------
    async def page(_request):
        return web.Response(text=PAGE, content_type="text/html", headers=SEC_HEADERS)

    async def login(request):
        ip, now = client_ip(request), time.time()
        FAILS[ip] = [t for t in FAILS.get(ip, []) if now - t < 600]
        total = sum(1 for v in FAILS.values() for t in v if now - t < 600)
        if len(FAILS[ip]) >= 5 or total >= 30:
            raise ApiError("محاولات كثيرة، استنى 10 دقايق", 429)
        data = await body(request)
        if not hmac.compare_digest(str(data.get("password", "")).encode(), password.encode()):
            FAILS[ip].append(now)
            raise ApiError("كلمة السر غلط", 401)
        ts = str(int(now))
        resp = web.json_response({"ok": True})
        secure = request.headers.get("X-Forwarded-Proto", request.scheme) == "https"
        resp.set_cookie(
            COOKIE, f"{ts}.{sign(ts)}", max_age=SESSION_TTL,
            httponly=True, secure=secure, samesite="Strict", path="/",
        )
        audit("تسجيل دخول", ip)
        return resp

    async def logout(_request):
        resp = web.json_response({"ok": True})
        resp.del_cookie(COOKIE, path="/")
        return resp

    async def me(_request):
        return web.json_response({"ok": True, "bot": str(bot.user), "ping": round(bot.latency * 1000)})

    async def guilds(_request):
        return web.json_response({
            "guilds": [{"id": str(g.id), "name": g.name} for g in bot.guilds]
        })

    # ---------------- بيانات السيرفر ----------------
    async def info(request):
        g = get_guild(request)
        me_top = g.me.top_role
        roles = [
            {
                "id": str(r.id), "name": r.name,
                "safe": role_is_safe(r), "assignable": r < me_top,
            }
            for r in reversed(g.roles) if not r.is_default()
        ]
        return web.json_response({
            "name": g.name,
            "icon": g.icon.url if g.icon else None,
            "members": g.member_count,
            "text_count": len(g.text_channels),
            "voice_count": len(g.voice_channels),
            "role_count": len(g.roles),
            "boosts": g.premium_subscription_count,
            "ping": round(bot.latency * 1000),
            "channels": [
                {"id": str(c.id), "name": c.name, "category": c.category.name if c.category else ""}
                for c in g.text_channels
            ],
            "roles": roles,
        })

    async def members(request):
        g = get_guild(request)
        q = request.query.get("q", "").strip().lower()[:50]
        out = []
        if q:
            for m in g.members:
                if q in m.name.lower() or q in m.display_name.lower() or q == str(m.id):
                    out.append({"id": str(m.id), "name": m.name, "display": m.display_name, "bot": m.bot})
                    if len(out) >= 25:
                        break
        return web.json_response({"members": out})

    # ---------------- الإجراءات ----------------
    async def send(request):
        g, d = get_guild(request), await body(request)
        ch = text_channel(g, d.get("channel_id"))
        content = str(d.get("content", "")).strip()
        mention = bool(d.get("mention_everyone"))
        emb = d.get("embed")
        embed = None
        if isinstance(emb, dict):
            title = str(emb.get("title", "")).strip()[:256]
            desc = str(emb.get("description", "")).strip()[:4000]
            if title or desc:
                embed = discord.Embed(title=title or None, description=desc or None,
                                      color=parse_color(emb.get("color")))
        if mention:
            content = f"@everyone {content}".strip()
        if not content and not embed:
            raise ApiError("اكتب رسالة أول")
        if len(content) > 2000:
            raise ApiError("الرسالة أطول من 2000 حرف")
        await ch.send(
            content=content or None, embed=embed,
            allowed_mentions=discord.AllowedMentions(everyone=mention, users=False, roles=False),
        )
        audit("إرسال رسالة", f"#{ch.name}")
        return web.json_response({"ok": True})

    async def dm(request):
        g, d = get_guild(request), await body(request)
        m = g.get_member(to_int(d.get("user_id"), "العضو"))
        text = str(d.get("text", "")).strip()
        if m is None:
            raise ApiError("العضو مش موجود")
        if not text or len(text) > 2000:
            raise ApiError("الرسالة فاضية أو أطول من 2000 حرف")
        try:
            await m.send(text)
        except discord.Forbidden:
            raise ApiError("الخاص مقفول عند العضو")
        audit("رسالة خاصة", f"إلى {m}")
        return web.json_response({"ok": True})

    async def mod(request):
        g, d = get_guild(request), await body(request)
        action = d.get("action")
        reason = (str(d.get("reason") or "").strip() or "من لوحة التحكم")[:300]
        uid = to_int(d.get("user_id"), "العضو")

        if action == "unban":
            try:
                await g.unban(discord.Object(id=uid), reason=reason)
            except discord.NotFound:
                raise ApiError("هذا العضو مش محظور")
            audit("فك حظر", str(uid))
            await log_to_discord(g, "فك حظر من لوحة التحكم", f"<@{uid}>")
            return web.json_response({"ok": True})

        if action not in ("kick", "ban", "timeout", "untimeout"):
            raise ApiError("إجراء غير معروف")
        m = g.get_member(uid)
        if m is None:
            raise ApiError("العضو مش موجود")
        if m == g.owner or m.id == bot.user.id:
            raise ApiError("ما تقدرش تعمل هذا على هالعضو")
        if m.top_role >= g.me.top_role:
            raise ApiError("رتبة البوت لازم تكون فوق رتبة العضو")

        if action == "kick":
            await m.kick(reason=reason)
        elif action == "ban":
            await m.ban(reason=reason)
        elif action == "timeout":
            minutes = to_int(d.get("minutes"), "المدة")
            if not 1 <= minutes <= 40320:
                raise ApiError("المدة من 1 إلى 40320 دقيقة")
            await m.timeout(datetime.timedelta(minutes=minutes), reason=reason)
        else:
            await m.timeout(None, reason=reason)
        audit(action, f"{m} — {reason}")
        await log_to_discord(g, f"{action} من لوحة التحكم", f"{m.mention} — {reason}")
        return web.json_response({"ok": True})

    async def clear(request):
        g, d = get_guild(request), await body(request)
        ch = text_channel(g, d.get("channel_id"))
        amount = to_int(d.get("amount"), "العدد")
        if not 1 <= amount <= 100:
            raise ApiError("العدد من 1 إلى 100")
        deleted = await ch.purge(limit=amount)
        audit("مسح رسائل", f"#{ch.name}: {len(deleted)}")
        return web.json_response({"ok": True, "deleted": len(deleted)})

    # ---------------- الردود التلقائية ----------------
    async def ar_list(request):
        g = get_guild(request)
        items = deps["autoreplies"].get(g.id, {})
        return web.json_response({"items": [{"trigger": t, "reply": r} for t, r in items.items()]})

    async def ar_add(request):
        g, d = get_guild(request), await body(request)
        trigger = str(d.get("trigger", "")).strip().lower()[:100]
        reply = str(d.get("reply", "")).strip()[:1500]
        if not trigger or not reply:
            raise ApiError("اكتب الكلمة والرد")
        deps["autoreplies"].setdefault(g.id, {})[trigger] = reply
        rules = deps.get("rules")
        if rules is not None:
            await rules.update_one({"guild_id": g.id, "trigger": trigger}, {"$set": {"reply": reply}}, upsert=True)
        audit("رد تلقائي (إضافة)", trigger)
        return web.json_response({"ok": True, "persisted": rules is not None})

    async def ar_remove(request):
        g, d = get_guild(request), await body(request)
        trigger = str(d.get("trigger", "")).strip().lower()
        if deps["autoreplies"].get(g.id, {}).pop(trigger, None) is None:
            raise ApiError("الكلمة مش موجودة")
        rules = deps.get("rules")
        if rules is not None:
            await rules.delete_one({"guild_id": g.id, "trigger": trigger})
        audit("رد تلقائي (حذف)", trigger)
        return web.json_response({"ok": True})

    # ---------------- اللوحات ----------------
    async def panel(request):
        g, d = get_guild(request), await body(request)
        ch = text_channel(g, d.get("channel_id"))
        title = str(d.get("title", "")).strip()[:256]
        kind = d.get("type")
        if kind == "ticket":
            embed = discord.Embed(
                title=title or "🎫 الدعم الفني",
                description="محتاج مساعدة؟ دوس الزر تحت وتفتح تذكرة خاصة مع فريق الدعم.",
                color=discord.Color.blurple(),
            )
            await ch.send(embed=embed, view=deps["TicketPanel"]())
        elif kind == "roles":
            ids = d.get("role_ids")
            if not isinstance(ids, list) or not 1 <= len(ids) <= 10:
                raise ApiError("اختار من 1 إلى 10 رتب")
            view = discord.ui.View(timeout=None)
            for rid in ids:
                r = g.get_role(to_int(rid, "الرتبة"))
                if r is None or not role_is_safe(r):
                    raise ApiError("رتبة غير صالحة أو فيها صلاحيات إدارة")
                view.add_item(deps["RoleButton"](r.id, r.name))
            embed = discord.Embed(
                title=title or "🎭 اختار رتبتك",
                description="دوس على الزر عشان تاخذ الرتبة أو تشيلها",
                color=discord.Color.blurple(),
            )
            await ch.send(embed=embed, view=view)
        else:
            raise ApiError("نوع اللوحة غير معروف")
        audit("إرسال لوحة", f"{kind} في #{ch.name}")
        return web.json_response({"ok": True})

    async def audit_list(_request):
        return web.json_response({"items": list(AUDIT)})

    r = app.router
    r.add_get("/dashboard", page)
    r.add_post("/api/login", login)
    r.add_post("/api/logout", logout)
    r.add_get("/api/me", me)
    r.add_get("/api/guilds", guilds)
    r.add_get("/api/guild/{gid}/info", info)
    r.add_get("/api/guild/{gid}/members", members)
    r.add_post("/api/guild/{gid}/send", send)
    r.add_post("/api/guild/{gid}/dm", dm)
    r.add_post("/api/guild/{gid}/mod", mod)
    r.add_post("/api/guild/{gid}/clear", clear)
    r.add_get("/api/guild/{gid}/autoreplies", ar_list)
    r.add_post("/api/guild/{gid}/autoreplies/add", ar_add)
    r.add_post("/api/guild/{gid}/autoreplies/remove", ar_remove)
    r.add_post("/api/guild/{gid}/panel", panel)
    r.add_get("/api/audit", audit_list)
    print("✅ لوحة التحكم شغالة على /dashboard")


PAGE = r"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>لوحة تحكم البوت</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--text:#e8eaf0;--mut:#8b93a7;--acc:#5865f2;--ok:#2ecc71;--err:#ed4245}
@media(prefers-color-scheme:light){:root{--bg:#f4f5f8;--card:#fff;--line:#e2e5ec;--text:#1b1f2a;--mut:#667085}}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,"Segoe UI",Tahoma,Arial,sans-serif;background:var(--bg);color:var(--text)}
.hidden{display:none!important}
.center{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px}
.narrow{width:100%;max-width:360px}
h2{margin:0 0 14px;font-size:20px}
label{display:block;margin:12px 0 6px;color:var(--mut);font-size:14px}
label.chk{display:flex;align-items:center;gap:8px;color:var(--text)}
input,select,textarea{width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text);font:inherit}
input[type=checkbox]{width:auto}
input[type=color]{height:42px;padding:4px}
textarea{resize:vertical}
button{font:inherit;cursor:pointer;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--text);padding:10px 14px}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff;margin-top:14px}
button.danger{background:var(--err);border-color:var(--err);color:#fff}
button.ghost{background:transparent}
button:disabled{opacity:.6;cursor:wait}
.mut{color:var(--mut)}
#app{display:flex;min-height:100vh}
aside{width:230px;padding:16px;border-left:1px solid var(--line);background:var(--card);display:flex;flex-direction:column;gap:10px}
.brand{font-weight:700;font-size:18px}
nav{display:flex;flex-direction:column;gap:6px;flex:1}
nav button{text-align:right;border-color:transparent;background:transparent}
nav button.active{background:var(--acc);color:#fff}
main{flex:1;padding:22px;max-width:900px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.stat{background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:14px;text-align:center}
.stat b{display:block;font-size:24px}
.list .item{padding:9px 12px;border:1px solid var(--line);border-radius:10px;margin-top:6px;cursor:pointer;background:var(--bg)}
.list .item:hover{border-color:var(--acc)}
.sel{margin-top:8px;padding:8px 12px;border-radius:10px;background:var(--bg);border:1px dashed var(--acc)}
.row{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--line)}
.row:last-child{border:0}
.row span{overflow-wrap:anywhere}
.roles{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:6px}
#toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);padding:11px 18px;border-radius:10px;color:#fff;opacity:0;transition:opacity .25s;pointer-events:none;z-index:9}
#toast.ok{background:var(--ok)}#toast.err{background:var(--err)}
@media(max-width:800px){#app{flex-direction:column}aside{width:100%;border-left:0;border-bottom:1px solid var(--line)}nav{flex-direction:row;overflow-x:auto}nav button{white-space:nowrap}}
</style>
</head>
<body>
<div id="login" class="center hidden">
  <form class="card narrow" id="loginForm">
    <h2>🔐 لوحة تحكم البوت</h2>
    <p class="mut">أدخل كلمة السر للدخول</p>
    <input type="password" id="pw" placeholder="كلمة السر" autocomplete="current-password" required>
    <button class="primary" type="submit" style="width:100%">دخول</button>
  </form>
</div>

<div id="app" class="hidden">
  <aside>
    <div class="brand">🤖 لوحة التحكم</div>
    <select id="guildSel"></select>
    <nav>
      <button data-p="overview" class="active">📊 نظرة عامة</button>
      <button data-p="send">📢 إرسال رسالة</button>
      <button data-p="dm">✉️ رسالة خاصة</button>
      <button data-p="mod">🔨 إشراف</button>
      <button data-p="auto">🤖 ردود تلقائية</button>
      <button data-p="panels">🎛️ لوحات</button>
      <button data-p="audit">📜 السجل</button>
    </nav>
    <button id="logout" class="ghost">تسجيل خروج</button>
  </aside>
  <main>
    <section id="p-overview">
      <h2 id="gname"></h2>
      <div class="card"><div class="grid" id="stats"></div></div>
    </section>

    <section id="p-send" class="hidden">
      <h2>📢 إرسال رسالة / إعلان</h2>
      <div class="card">
        <label>الروم</label><select id="s-channel"></select>
        <label>النص</label><textarea id="s-content" rows="4" maxlength="2000"></textarea>
        <label class="chk"><input type="checkbox" id="s-embed"> إرسال كإعلان (Embed)</label>
        <div id="s-embedbox" class="hidden">
          <label>العنوان</label><input id="s-title" maxlength="256">
          <label>الوصف</label><textarea id="s-desc" rows="4" maxlength="4000"></textarea>
          <label>اللون</label><input type="color" id="s-color" value="#f1c40f">
        </div>
        <label class="chk"><input type="checkbox" id="s-everyone"> منشن @everyone</label>
        <button class="primary" id="s-btn">إرسال</button>
      </div>
    </section>

    <section id="p-dm" class="hidden">
      <h2>✉️ رسالة في الخاص</h2>
      <div class="card">
        <label>ابحث عن العضو</label><input id="d-search" placeholder="اكتب الاسم أو الآيدي">
        <div class="list" id="d-list"></div>
        <div class="sel hidden" id="d-sel"></div>
        <label>الرسالة</label><textarea id="d-text" rows="4" maxlength="2000"></textarea>
        <button class="primary" id="d-btn">إرسال</button>
      </div>
    </section>

    <section id="p-mod" class="hidden">
      <h2>🔨 إشراف</h2>
      <div class="card">
        <label>ابحث عن العضو</label><input id="m-search" placeholder="اكتب الاسم أو الآيدي">
        <div class="list" id="m-list"></div>
        <div class="sel hidden" id="m-sel"></div>
        <label>الإجراء</label>
        <select id="m-action">
          <option value="timeout">كتم مؤقت (Timeout)</option>
          <option value="untimeout">إلغاء الكتم</option>
          <option value="kick">طرد</option>
          <option value="ban">حظر</option>
        </select>
        <div id="m-minutesbox"><label>المدة بالدقايق</label><input type="number" id="m-minutes" value="10" min="1" max="40320"></div>
        <label>السبب</label><input id="m-reason" maxlength="300">
        <button class="primary danger" id="m-btn">تنفيذ</button>
      </div>
      <div class="card">
        <h2>فك حظر</h2>
        <label>آيدي العضو</label><input id="u-id" placeholder="أرقام فقط">
        <button class="primary" id="u-btn">فك الحظر</button>
      </div>
      <div class="card">
        <h2>مسح رسائل</h2>
        <label>الروم</label><select id="c-channel"></select>
        <label>العدد (1 - 100)</label><input type="number" id="c-amount" value="10" min="1" max="100">
        <button class="primary danger" id="c-btn">مسح</button>
      </div>
    </section>

    <section id="p-auto" class="hidden">
      <h2>🤖 ردود تلقائية</h2>
      <div class="card">
        <label>الكلمة</label><input id="a-trigger" maxlength="100">
        <label>رد البوت</label><textarea id="a-reply" rows="3" maxlength="1500"></textarea>
        <button class="primary" id="a-btn">إضافة</button>
        <p class="mut">الرد يشتغل لو MESSAGE_CONTENT=1 وفعّلت Message Content Intent.</p>
      </div>
      <div class="card" id="a-list"></div>
    </section>

    <section id="p-panels" class="hidden">
      <h2>🎛️ لوحات</h2>
      <div class="card">
        <h2>🎫 لوحة التذاكر</h2>
        <label>الروم</label><select id="t-channel"></select>
        <label>العنوان (اختياري)</label><input id="t-title" maxlength="256">
        <button class="primary" id="t-btn">إرسال اللوحة</button>
      </div>
      <div class="card">
        <h2>🎭 لوحة الرتب</h2>
        <label>الروم</label><select id="r-channel"></select>
        <label>العنوان (اختياري)</label><input id="r-title" maxlength="256">
        <label>اختار الرتب (الرتب الآمنة وتحت رتبة البوت بس)</label>
        <div class="roles" id="r-roles"></div>
        <button class="primary" id="r-btn">إرسال اللوحة</button>
      </div>
    </section>

    <section id="p-audit" class="hidden">
      <h2>📜 سجل العمليات</h2>
      <div class="card" id="au-list"></div>
    </section>
  </main>
</div>
<div id="toast"></div>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let G = null, INFO = null, DM_USER = null, MOD_USER = null;

function toast(msg, ok = true) {
  const t = $('#toast');
  t.textContent = msg; t.className = ok ? 'ok' : 'err'; t.style.opacity = 1;
  clearTimeout(toast.h); toast.h = setTimeout(() => t.style.opacity = 0, 3500);
}

async function api(path, method = 'GET', body) {
  const opt = {method, credentials: 'same-origin'};
  if (method !== 'GET') { opt.headers = {'Content-Type': 'application/json'}; opt.body = JSON.stringify(body || {}); }
  const r = await fetch('/api' + path, opt);
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (r.status === 401 && path !== '/login') { showLogin(); throw new Error('سجّل دخول من جديد'); }
  if (!r.ok) throw new Error(data.error || 'صار خطأ');
  return data;
}

async function run(btn, fn, okMsg) {
  btn.disabled = true;
  try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
  catch (e) { toast(e.message, false); }
  finally { btn.disabled = false; }
}

function showLogin() { $('#app').classList.add('hidden'); $('#login').classList.remove('hidden'); }

function go(p) {
  document.querySelectorAll('main section').forEach(s => s.classList.add('hidden'));
  $('#p-' + p).classList.remove('hidden');
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.p === p));
  if (p === 'auto') loadAuto();
  if (p === 'audit') loadAudit();
}

function fillChannels(ids) {
  ids.forEach(id => {
    const sel = $(id); sel.innerHTML = '';
    INFO.channels.forEach(c => {
      const o = document.createElement('option');
      o.value = c.id; o.textContent = '# ' + c.name + (c.category ? '  (' + c.category + ')' : '');
      sel.appendChild(o);
    });
  });
}

async function loadInfo() {
  INFO = await api('/guild/' + G + '/info');
  $('#gname').textContent = INFO.name;
  const stats = [['👥 الأعضاء', INFO.members], ['💬 رومات نصية', INFO.text_count], ['🔊 رومات صوتية', INFO.voice_count],
                 ['🎭 الرتب', INFO.role_count], ['🚀 البوستات', INFO.boosts], ['📡 البنق', INFO.ping + 'ms']];
  $('#stats').innerHTML = stats.map(s => '<div class="stat"><b>' + esc(s[1]) + '</b>' + esc(s[0]) + '</div>').join('');
  fillChannels(['#s-channel', '#c-channel', '#t-channel', '#r-channel']);
  const box = $('#r-roles'); box.innerHTML = '';
  INFO.roles.filter(r => r.safe && r.assignable).forEach(r => {
    const l = document.createElement('label'); l.className = 'chk';
    const i = document.createElement('input'); i.type = 'checkbox'; i.value = r.id;
    l.appendChild(i); l.appendChild(document.createTextNode(' ' + r.name)); box.appendChild(l);
  });
}

function picker(inp, list, onPick) {
  let h;
  inp.oninput = () => {
    clearTimeout(h);
    h = setTimeout(async () => {
      const q = inp.value.trim();
      list.innerHTML = '';
      if (!q) return;
      try {
        const r = await api('/guild/' + G + '/members?q=' + encodeURIComponent(q));
        r.members.forEach(m => {
          const d = document.createElement('div'); d.className = 'item';
          d.textContent = m.display + ' (' + m.name + ')' + (m.bot ? ' 🤖' : '');
          d.onclick = () => { onPick(m); list.innerHTML = ''; inp.value = ''; };
          list.appendChild(d);
        });
        if (!r.members.length) list.textContent = 'ما لقيتش حد';
      } catch (e) { toast(e.message, false); }
    }, 300);
  };
}

function setSel(box, m) { box.textContent = 'المحدد: ' + m.display + ' (' + m.name + ')'; box.classList.remove('hidden'); }

async function loadAuto() {
  const box = $('#a-list');
  try {
    const r = await api('/guild/' + G + '/autoreplies');
    box.innerHTML = '';
    if (!r.items.length) { box.textContent = 'ما فيش ردود لسه'; return; }
    r.items.forEach(it => {
      const row = document.createElement('div'); row.className = 'row';
      const sp = document.createElement('span'); sp.textContent = it.trigger + '  ←  ' + it.reply;
      const b = document.createElement('button'); b.className = 'danger'; b.textContent = 'حذف';
      b.onclick = () => run(b, async () => { await api('/guild/' + G + '/autoreplies/remove', 'POST', {trigger: it.trigger}); loadAuto(); }, 'تم الحذف');
      row.appendChild(sp); row.appendChild(b); box.appendChild(row);
    });
  } catch (e) { toast(e.message, false); }
}

async function loadAudit() {
  const box = $('#au-list');
  try {
    const r = await api('/audit');
    box.innerHTML = '';
    if (!r.items.length) { box.textContent = 'ما فيش عمليات لسه'; return; }
    r.items.forEach(it => {
      const row = document.createElement('div'); row.className = 'row';
      const sp = document.createElement('span'); sp.textContent = it.action + ' — ' + it.detail;
      const t = document.createElement('span'); t.className = 'mut'; t.textContent = new Date(it.t * 1000).toLocaleString('ar');
      row.appendChild(sp); row.appendChild(t); box.appendChild(row);
    });
  } catch (e) { toast(e.message, false); }
}

async function init() {
  try {
    await api('/me');
    const r = await api('/guilds');
    if (!r.guilds.length) { toast('البوت مش في أي سيرفر', false); }
    const sel = $('#guildSel'); sel.innerHTML = '';
    r.guilds.forEach(g => { const o = document.createElement('option'); o.value = g.id; o.textContent = g.name; sel.appendChild(o); });
    G = sel.value;
    $('#login').classList.add('hidden'); $('#app').classList.remove('hidden');
    if (G) await loadInfo();
  } catch (e) { showLogin(); }
}

$('#loginForm').onsubmit = async ev => {
  ev.preventDefault();
  try { await api('/login', 'POST', {password: $('#pw').value}); $('#pw').value = ''; init(); }
  catch (e) { toast(e.message, false); }
};
$('#logout').onclick = async () => { await api('/logout', 'POST'); showLogin(); };
$('#guildSel').onchange = async e => { G = e.target.value; await loadInfo(); };
document.querySelectorAll('nav button').forEach(b => b.onclick = () => go(b.dataset.p));

$('#s-embed').onchange = e => $('#s-embedbox').classList.toggle('hidden', !e.target.checked);
$('#s-btn').onclick = ev => run(ev.target, async () => {
  const body = {channel_id: $('#s-channel').value, content: $('#s-content').value, mention_everyone: $('#s-everyone').checked};
  if ($('#s-embed').checked) body.embed = {title: $('#s-title').value, description: $('#s-desc').value, color: $('#s-color').value};
  await api('/guild/' + G + '/send', 'POST', body);
  $('#s-content').value = ''; $('#s-title').value = ''; $('#s-desc').value = '';
}, 'تم الإرسال ✅');

picker($('#d-search'), $('#d-list'), m => { DM_USER = m; setSel($('#d-sel'), m); });
$('#d-btn').onclick = ev => run(ev.target, async () => {
  if (!DM_USER) throw new Error('اختار عضو أول');
  await api('/guild/' + G + '/dm', 'POST', {user_id: DM_USER.id, text: $('#d-text').value});
  $('#d-text').value = '';
}, 'انبعتت ✅');

picker($('#m-search'), $('#m-list'), m => { MOD_USER = m; setSel($('#m-sel'), m); });
$('#m-action').onchange = e => $('#m-minutesbox').classList.toggle('hidden', e.target.value !== 'timeout');
$('#m-btn').onclick = ev => run(ev.target, async () => {
  if (!MOD_USER) throw new Error('اختار عضو أول');
  const action = $('#m-action').value;
  if (['kick', 'ban'].includes(action) && !confirm('متأكد؟ ' + action + ' ' + MOD_USER.display)) return;
  await api('/guild/' + G + '/mod', 'POST', {action, user_id: MOD_USER.id, minutes: $('#m-minutes').value, reason: $('#m-reason').value});
  toast('تم التنفيذ ✅');
});
$('#u-btn').onclick = ev => run(ev.target, async () => {
  await api('/guild/' + G + '/mod', 'POST', {action: 'unban', user_id: $('#u-id').value.trim()});
  $('#u-id').value = '';
}, 'تم فك الحظر ✅');
$('#c-btn').onclick = ev => run(ev.target, async () => {
  if (!confirm('تمسح الرسائل؟')) return;
  const r = await api('/guild/' + G + '/clear', 'POST', {channel_id: $('#c-channel').value, amount: $('#c-amount').value});
  toast('اتمسحت ' + r.deleted + ' رسالة ✅');
});

$('#a-btn').onclick = ev => run(ev.target, async () => {
  const r = await api('/guild/' + G + '/autoreplies/add', 'POST', {trigger: $('#a-trigger').value, reply: $('#a-reply').value});
  $('#a-trigger').value = ''; $('#a-reply').value = ''; loadAuto();
  if (!r.persisted) toast('تمت الإضافة (بدون MONGO_URI تضيع عند إعادة التشغيل)');
  else toast('تمت الإضافة ✅');
});

$('#t-btn').onclick = ev => run(ev.target, () => api('/guild/' + G + '/panel', 'POST', {type: 'ticket', channel_id: $('#t-channel').value, title: $('#t-title').value}), 'تم إرسال لوحة التذاكر ✅');
$('#r-btn').onclick = ev => run(ev.target, () => {
  const ids = [...document.querySelectorAll('#r-roles input:checked')].map(i => i.value);
  return api('/guild/' + G + '/panel', 'POST', {type: 'roles', channel_id: $('#r-channel').value, title: $('#r-title').value, role_ids: ids});
}, 'تم إرسال لوحة الرتب ✅');

init();
</script>
</body>
</html>
"""
