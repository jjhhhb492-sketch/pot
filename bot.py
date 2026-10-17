import asyncio
import datetime
import os
import random
import re
import time

import discord
from aiohttp import web
from discord import app_commands
from dotenv import load_dotenv

import dashboard

load_dotenv()


def env_int(name: str) -> int:
    v = os.getenv(name, "")
    return int(v) if v.isdigit() else 0


TOKEN = os.getenv("DISCORD_TOKEN")
SERVER_NAME = os.getenv("SERVER_NAME", "السيرفر")
WELCOME_CHANNEL_ID = env_int("WELCOME_CHANNEL_ID")
LEAVE_CHANNEL_ID = env_int("LEAVE_CHANNEL_ID") or WELCOME_CHANNEL_ID
AUTO_ROLE_ID = env_int("AUTO_ROLE_ID")
SUPPORT_ROLE_ID = env_int("SUPPORT_ROLE_ID")
TICKET_CATEGORY_ID = env_int("TICKET_CATEGORY_ID")
LOG_CHANNEL_ID = env_int("LOG_CHANNEL_ID")
STARBOARD_CHANNEL_ID = env_int("STARBOARD_CHANNEL_ID")
STAR_COUNT = env_int("STAR_COUNT") or 3
TEMP_VOICE_ID = env_int("TEMP_VOICE_CHANNEL_ID")
ANTI_LINK = os.getenv("ANTI_LINK") == "1"
MESSAGE_CONTENT = os.getenv("MESSAGE_CONTENT") == "1"
MONGO_URI = os.getenv("MONGO_URI")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")

TEMP_PREFIX = "🔊 "
LINK_RE = re.compile(r"(https?://|discord\.gg/|discord(app)?\.com/invite/)", re.I)

# ---------- قاعدة البيانات (اختيارية: للفلات والمكافأة والردود التلقائية) ----------
users = None
rules = None
if MONGO_URI:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo import ReturnDocument

    _db = AsyncIOMotorClient(MONGO_URI)["discordbot"]
    users = _db["users"]
    rules = _db["autoreplies"]

NO_DB_MSG = "❌ هذا النظام غير مفعّل لسه (ناقص MONGO_URI)"

autoreplies: dict[int, dict[str, str]] = {}  # guild_id -> {trigger: reply}
starred: set[int] = set()
xp_cooldown: dict[int, float] = {}


def level_for(xp: int) -> int:
    return int((xp / 100) ** 0.5)


def xp_for_level(level: int) -> int:
    return 100 * level * level


intents = discord.Intents.default()
intents.members = True  # لازم Server Members Intent
intents.message_content = MESSAGE_CONTENT  # لازم Message Content Intent لو MESSAGE_CONTENT=1


async def send_log(guild: discord.Guild, embed: discord.Embed):
    if not LOG_CHANNEL_ID:
        return
    ch = guild.get_channel(LOG_CHANNEL_ID)
    if ch:
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass


def can_act(interaction: discord.Interaction, target: discord.Member) -> bool:
    g = interaction.guild
    if target == g.owner or target.id == interaction.user.id:
        return False
    if interaction.user == g.owner:
        return True
    return interaction.user.top_role > target.top_role


# ---------- التذاكر ----------
class CloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 إغلاق التذكرة", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        ch = interaction.channel
        topic = getattr(ch, "topic", "") or ""
        if not topic.startswith("ticket:"):
            return await interaction.response.send_message("❌ هذي مش تذكرة", ephemeral=True)

        support = interaction.guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None
        is_owner = topic == f"ticket:{interaction.user.id}"
        is_staff = interaction.user.guild_permissions.manage_channels or (
            support is not None and support in interaction.user.roles
        )
        if not (is_owner or is_staff):
            return await interaction.response.send_message("❌ ما عندكش صلاحية", ephemeral=True)

        await interaction.response.send_message("🔒 التذكرة تتقفل بعد 5 ثواني...")
        await asyncio.sleep(5)
        await ch.delete(reason=f"Ticket closed by {interaction.user}")


class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 فتح تذكرة", style=discord.ButtonStyle.green, custom_id="ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild, user = interaction.guild, interaction.user
        await interaction.response.defer(ephemeral=True)

        for ch in guild.text_channels:
            if ch.topic == f"ticket:{user.id}":
                return await interaction.followup.send(f"عندك تذكرة مفتوحة: {ch.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        support = guild.get_role(SUPPORT_ROLE_ID) if SUPPORT_ROLE_ID else None
        if support:
            overwrites[support] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        category = guild.get_channel(TICKET_CATEGORY_ID) if TICKET_CATEGORY_ID else None
        if not isinstance(category, discord.CategoryChannel):
            category = None

        channel = await guild.create_text_channel(
            f"ticket-{user.name}",
            overwrites=overwrites,
            category=category,
            topic=f"ticket:{user.id}",
        )
        embed = discord.Embed(
            title="🎫 تذكرة جديدة",
            description=f"أهلاً {user.mention}، اكتب مشكلتك وفريق الدعم يرد عليك قريب.",
            color=discord.Color.blurple(),
        )
        await channel.send(content=support.mention if support else None, embed=embed, view=CloseView())
        await interaction.followup.send(f"✅ تم فتح تذكرتك: {channel.mention}", ephemeral=True)


# ---------- أزرار الرتب (Role Panel) ----------
class RoleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"role:(?P<id>[0-9]+)"):
    def __init__(self, role_id: int, label: str = "رتبة"):
        super().__init__(
            discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"role:{role_id}")
        )
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match, /):
        return cls(int(match["id"]), item.label or "رتبة")

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            return await interaction.response.send_message("❌ الرتبة ما عادش موجودة", ephemeral=True)
        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role)
                msg = f"➖ اتشالت منك رتبة **{role.name}**"
            else:
                await interaction.user.add_roles(role)
                msg = f"➕ خذت رتبة **{role.name}**"
        except discord.Forbidden:
            msg = "❌ ما نقدرش نعطي الرتبة: رتبة البوت لازم تكون فوقها"
        await interaction.response.send_message(msg, ephemeral=True)


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.add_view(TicketPanel())
        self.add_view(CloseView())
        self.add_dynamic_items(RoleButton)

        if rules is not None:
            try:
                async for d in rules.find({}):
                    autoreplies.setdefault(d["guild_id"], {})[d["trigger"]] = d["reply"]
            except Exception as e:
                print("⚠️ ما قدرناش نحمّل الردود التلقائية:", e)

        await self.tree.sync()

        # سيرفر صغير عشان Render يشوف بورت مفتوح + UptimeRobot يعمل ping
        async def health(_request):
            return web.Response(text="Bot is running ✅")

        app = web.Application()
        app.router.add_get("/", health)
        if DASHBOARD_PASSWORD:
            dashboard.register(
                app, self,
                {
                    "autoreplies": autoreplies,
                    "rules": rules,
                    "TicketPanel": TicketPanel,
                    "RoleButton": RoleButton,
                    "send_log": send_log,
                },
                TOKEN, DASHBOARD_PASSWORD,
            )
        else:
            print("ℹ️ لوحة التحكم مقفولة: زيد DASHBOARD_PASSWORD عشان تفتحها")
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv("PORT", "8080"))
        await web.TCPSite(runner, "0.0.0.0", port).start()


bot = Bot()


@bot.event
async def on_ready():
    print(f"✅ البوت شغال: {bot.user}")


@bot.tree.error
async def on_app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ ما عندكش صلاحية لهذا الأمر"
    else:
        msg = "❌ صار خطأ، حاول مرة ثانية"
        print("خطأ في أمر:", repr(error))
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


# ================= الترحيب + الرتبة التلقائية + المغادرة =================
@bot.event
async def on_member_join(member: discord.Member):
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title=f"أهلاً بيك في {SERVER_NAME} 👋",
            description=f"نورتنا يا {member.mention}\nأنت العضو رقم {member.guild.member_count}",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

    try:
        await member.send(f"أهلاً بيك {member.name} في **{SERVER_NAME}** 🎉\nاقرا القوانين وتمتع معانا!")
    except discord.Forbidden:
        pass

    if AUTO_ROLE_ID:
        role = member.guild.get_role(AUTO_ROLE_ID)
        if role:
            try:
                await member.add_roles(role, reason="Auto role")
            except discord.Forbidden:
                print("⚠️ ما نقدرش نعطي الرتبة: ارفع رتبة البوت فوق الرتبة التلقائية")


@bot.event
async def on_member_remove(member: discord.Member):
    channel = member.guild.get_channel(LEAVE_CHANNEL_ID)
    if channel:
        await channel.send(f"👋 **{member.display_name}** غادر السيرفر. نشوفوك على خير!")


# ================= الرسائل: حظر الروابط + الرد التلقائي + XP =================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    # حظر الروابط (يحتاج MESSAGE_CONTENT=1)
    if ANTI_LINK and LINK_RE.search(message.content or ""):
        if not message.author.guild_permissions.manage_messages:
            try:
                await message.delete()
                await message.channel.send(f"🚫 {message.author.mention} الروابط ممنوعة هنا", delete_after=5)
            except discord.HTTPException:
                pass
            return

    # الرد التلقائي (يحتاج MESSAGE_CONTENT=1)
    content = (message.content or "").lower()
    if content:
        for trigger, reply in autoreplies.get(message.guild.id, {}).items():
            if trigger in content:
                await message.reply(reply, mention_author=False)
                break

    # اللفلات
    if users is None:
        return
    now = time.time()
    if now - xp_cooldown.get(message.author.id, 0) < 60:
        return
    xp_cooldown[message.author.id] = now

    gain = random.randint(15, 25)
    doc = await users.find_one_and_update(
        {"_id": f"{message.guild.id}-{message.author.id}"},
        {"$inc": {"xp": gain}, "$setOnInsert": {"guild_id": message.guild.id, "user_id": message.author.id}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    if level_for(doc["xp"]) > level_for(doc["xp"] - gain):
        await message.channel.send(f"🎉 مبروك {message.author.mention}! وصلت لفل **{level_for(doc['xp'])}**")


# ================= الرومات الصوتية المؤقتة =================
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if before.channel == after.channel:
        return
    try:
        if TEMP_VOICE_ID and after.channel and after.channel.id == TEMP_VOICE_ID:
            ch = await member.guild.create_voice_channel(
                f"{TEMP_PREFIX}{member.display_name}",
                category=after.channel.category,
                overwrites={member: discord.PermissionOverwrite(manage_channels=True, move_members=True)},
            )
            await member.move_to(ch)

        old = before.channel
        if old and old.id != TEMP_VOICE_ID and old.name.startswith(TEMP_PREFIX) and len(old.members) == 0:
            await old.delete(reason="Temp voice empty")
    except discord.HTTPException as e:
        print("⚠️ خطأ في الرومات المؤقتة:", e)


# ================= Starboard =================
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if not STARBOARD_CHANNEL_ID or not payload.guild_id or str(payload.emoji) != "⭐":
        return
    if payload.message_id in starred or payload.channel_id == STARBOARD_CHANNEL_ID:
        return
    channel = bot.get_channel(payload.channel_id)
    board = bot.get_channel(STARBOARD_CHANNEL_ID)
    if channel is None or board is None:
        return
    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.HTTPException:
        return
    reaction = discord.utils.get(message.reactions, emoji="⭐")
    if reaction is None or reaction.count < STAR_COUNT:
        return
    starred.add(message.id)
    embed = discord.Embed(description=message.content or "", color=discord.Color.gold())
    embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
    embed.add_field(name="الرسالة", value=f"[روح للرسالة]({message.jump_url})")
    if message.attachments:
        embed.set_image(url=message.attachments[0].url)
    await board.send(f"⭐ **{reaction.count}** | {channel.mention}", embed=embed)


# ================= اللوقات =================
@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or message.guild is None or message.channel.id == LOG_CHANNEL_ID:
        return
    embed = discord.Embed(title="🗑️ رسالة محذوفة", color=discord.Color.red())
    embed.add_field(name="الكاتب", value=message.author.mention)
    embed.add_field(name="الروم", value=message.channel.mention)
    embed.add_field(name="المحتوى", value=(message.content or "غير متاح")[:1000], inline=False)
    await send_log(message.guild, embed)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or before.guild is None or before.content == after.content:
        return
    embed = discord.Embed(title="✏️ رسالة معدّلة", color=discord.Color.orange())
    embed.add_field(name="الكاتب", value=before.author.mention)
    embed.add_field(name="الروم", value=before.channel.mention)
    embed.add_field(name="قبل", value=(before.content or "غير متاح")[:500], inline=False)
    embed.add_field(name="بعد", value=(after.content or "غير متاح")[:500], inline=False)
    await send_log(before.guild, embed)


@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    await send_log(guild, discord.Embed(title="🔨 حظر", description=f"{user} ({user.id})", color=discord.Color.dark_red()))


@bot.event
async def on_member_unban(guild: discord.Guild, user: discord.User):
    await send_log(guild, discord.Embed(title="✅ فك حظر", description=f"{user} ({user.id})", color=discord.Color.green()))


# ================= أوامر المعلومات =================
@bot.tree.command(name="user", description="معلومات عن عضو")
@app_commands.guild_only()
async def user_cmd(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    roles = [r.mention for r in reversed(member.roles) if r != interaction.guild.default_role][:10]
    embed = discord.Embed(title=str(member), color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="الآيدي", value=member.id)
    embed.add_field(name="فتح الحساب", value=discord.utils.format_dt(member.created_at, "R"))
    embed.add_field(name="دخل السيرفر", value=discord.utils.format_dt(member.joined_at, "R"))
    embed.add_field(name="الرتب", value=" ".join(roles) or "ما فيش", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="avatar", description="صورة عضو")
@app_commands.guild_only()
async def avatar_cmd(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"صورة {member.display_name}", color=member.color)
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="server", description="معلومات السيرفر")
@app_commands.guild_only()
async def server_cmd(interaction: discord.Interaction):
    g = interaction.guild
    embed = discord.Embed(title=g.name, color=discord.Color.blurple())
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    embed.add_field(name="المالك", value=g.owner.mention if g.owner else "؟")
    embed.add_field(name="الأعضاء", value=g.member_count)
    embed.add_field(name="الرومات", value=len(g.channels))
    embed.add_field(name="الرتب", value=len(g.roles))
    embed.add_field(name="البوستات", value=g.premium_subscription_count)
    embed.add_field(name="تم الإنشاء", value=discord.utils.format_dt(g.created_at, "R"))
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="profile", description="بطاقتك (لفل وXP وعملات)")
@app_commands.guild_only()
async def profile_cmd(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f"بطاقة {member.display_name}", color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="دخل السيرفر", value=discord.utils.format_dt(member.joined_at, "R"))
    if users is not None:
        doc = await users.find_one({"_id": f"{interaction.guild.id}-{member.id}"}) or {}
        xp = doc.get("xp", 0)
        lvl = level_for(xp)
        embed.add_field(name="اللفل", value=lvl)
        embed.add_field(name="XP", value=f"{xp} / {xp_for_level(lvl + 1)}")
        embed.add_field(name="العملات 🪙", value=doc.get("coins", 0))
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="moveme", description="ينقلك إلى روم صوتي")
@app_commands.guild_only()
async def moveme(interaction: discord.Interaction, channel: discord.VoiceChannel):
    if interaction.user.voice is None:
        return await interaction.response.send_message("❌ لازم تكون في روم صوتي أول", ephemeral=True)
    try:
        await interaction.user.move_to(channel)
        await interaction.response.send_message(f"✅ اتنقلت إلى {channel.mention}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ ما عنديش صلاحية أنقلك", ephemeral=True)


# ================= اللفلات والمكافأة =================
@bot.tree.command(name="rank", description="لفلك وXP")
@app_commands.guild_only()
async def rank_cmd(interaction: discord.Interaction, member: discord.Member = None):
    if users is None:
        return await interaction.response.send_message(NO_DB_MSG, ephemeral=True)
    member = member or interaction.user
    doc = await users.find_one({"_id": f"{interaction.guild.id}-{member.id}"}) or {}
    xp = doc.get("xp", 0)
    lvl = level_for(xp)
    await interaction.response.send_message(
        f"📊 **{member.display_name}** — لفل **{lvl}** — XP: **{xp}** / {xp_for_level(lvl + 1)}"
    )


@bot.tree.command(name="top", description="أعلى 10 أعضاء")
@app_commands.guild_only()
async def top_cmd(interaction: discord.Interaction):
    if users is None:
        return await interaction.response.send_message(NO_DB_MSG, ephemeral=True)
    lines = []
    i = 1
    async for d in users.find({"guild_id": interaction.guild.id}).sort("xp", -1).limit(10):
        lines.append(f"**{i}.** <@{d['user_id']}> — لفل {level_for(d['xp'])} ({d['xp']} XP)")
        i += 1
    embed = discord.Embed(title="🏆 المتصدرين", description="\n".join(lines) or "ما فيش أحد لسه", color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="daily", description="خذ مكافأتك اليومية")
@app_commands.guild_only()
async def daily_cmd(interaction: discord.Interaction):
    if users is None:
        return await interaction.response.send_message(NO_DB_MSG, ephemeral=True)
    key = f"{interaction.guild.id}-{interaction.user.id}"
    doc = await users.find_one({"_id": key}) or {}
    now = time.time()
    last = doc.get("last_daily", 0)
    if now - last < 86400:
        return await interaction.response.send_message(f"⏳ خذتها قبل، ارجع <t:{int(last + 86400)}:R>", ephemeral=True)

    reward = random.randint(100, 200)
    await users.update_one(
        {"_id": key},
        {
            "$inc": {"coins": reward},
            "$set": {"last_daily": now},
            "$setOnInsert": {"guild_id": interaction.guild.id, "user_id": interaction.user.id},
        },
        upsert=True,
    )
    await interaction.response.send_message(f"🎁 خذت **{reward}** عملة 🪙")


# ================= الإشراف (Moderation) =================
@bot.tree.command(name="kick", description="طرد عضو")
@app_commands.default_permissions(kick_members=True)
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.guild_only()
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    if not can_act(interaction, member):
        return await interaction.response.send_message("❌ ما تقدرش تعمل هذا على هالعضو", ephemeral=True)
    try:
        await member.kick(reason=f"{interaction.user}: {reason}")
    except discord.Forbidden:
        return await interaction.response.send_message("❌ رتبة البوت لازم تكون فوق العضو", ephemeral=True)
    await interaction.response.send_message(f"👢 تم طرد **{member}** — {reason}")


@bot.tree.command(name="ban", description="حظر عضو")
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.guild_only()
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    if not can_act(interaction, member):
        return await interaction.response.send_message("❌ ما تقدرش تعمل هذا على هالعضو", ephemeral=True)
    try:
        await member.ban(reason=f"{interaction.user}: {reason}")
    except discord.Forbidden:
        return await interaction.response.send_message("❌ رتبة البوت لازم تكون فوق العضو", ephemeral=True)
    await interaction.response.send_message(f"🔨 تم حظر **{member}** — {reason}")


@bot.tree.command(name="unban", description="فك حظر بالآيدي")
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.guild_only()
async def unban(interaction: discord.Interaction, user_id: str):
    if not user_id.isdigit():
        return await interaction.response.send_message("❌ اكتب الآيدي أرقام بس", ephemeral=True)
    try:
        await interaction.guild.unban(discord.Object(id=int(user_id)))
        await interaction.response.send_message("✅ تم فك الحظر")
    except discord.NotFound:
        await interaction.response.send_message("❌ هذا العضو مش محظور", ephemeral=True)


@bot.tree.command(name="timeout", description="كتم عضو لمدة (بالدقايق)")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def timeout_cmd(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: app_commands.Range[int, 1, 40320],
    reason: str = "بدون سبب",
):
    if not can_act(interaction, member):
        return await interaction.response.send_message("❌ ما تقدرش تعمل هذا على هالعضو", ephemeral=True)
    try:
        await member.timeout(datetime.timedelta(minutes=minutes), reason=f"{interaction.user}: {reason}")
    except discord.Forbidden:
        return await interaction.response.send_message("❌ رتبة البوت لازم تكون فوق العضو", ephemeral=True)
    await interaction.response.send_message(f"🔇 تم كتم **{member}** لمدة {minutes} دقيقة — {reason}")


@bot.tree.command(name="untimeout", description="إلغاء كتم عضو")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def untimeout(interaction: discord.Interaction, member: discord.Member):
    try:
        await member.timeout(None)
        await interaction.response.send_message(f"🔊 تم إلغاء كتم **{member}**")
    except discord.Forbidden:
        await interaction.response.send_message("❌ رتبة البوت لازم تكون فوق العضو", ephemeral=True)


@bot.tree.command(name="clear", description="مسح رسائل")
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.guild_only()
async def clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 اتمسحت {len(deleted)} رسالة", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ ما عنديش صلاحية Manage Messages في هالروم", ephemeral=True)


# ================= الردود التلقائية =================
@bot.tree.command(name="autoreply_add", description="إضافة رد تلقائي")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
@app_commands.describe(trigger="الكلمة اللي يرد عليها", reply="رد البوت")
async def autoreply_add(interaction: discord.Interaction, trigger: str, reply: str):
    gid = interaction.guild.id
    trigger = trigger.strip().lower()
    autoreplies.setdefault(gid, {})[trigger] = reply
    if rules is not None:
        await rules.update_one(
            {"guild_id": gid, "trigger": trigger}, {"$set": {"reply": reply}}, upsert=True
        )
    msg = f"✅ إذا أحد كتب **{trigger}** البوت يرد."
    if rules is None:
        msg += "\n⚠️ بدون MONGO_URI الردود تضيع لما البوت يعيد التشغيل."
    if not MESSAGE_CONTENT:
        msg += "\n⚠️ لازم تفعّل MESSAGE_CONTENT=1 عشان يقرا الرسائل."
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="autoreply_remove", description="حذف رد تلقائي")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def autoreply_remove(interaction: discord.Interaction, trigger: str):
    gid = interaction.guild.id
    trigger = trigger.strip().lower()
    if autoreplies.get(gid, {}).pop(trigger, None) is None:
        return await interaction.response.send_message("❌ ما لقيتش هالكلمة", ephemeral=True)
    if rules is not None:
        await rules.delete_one({"guild_id": gid, "trigger": trigger})
    await interaction.response.send_message("✅ تم الحذف", ephemeral=True)


@bot.tree.command(name="autoreply_list", description="عرض الردود التلقائية")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def autoreply_list(interaction: discord.Interaction):
    items = autoreplies.get(interaction.guild.id, {})
    text = "\n".join(f"• **{t}** ← {r[:50]}" for t, r in items.items()) or "ما فيش ردود لسه"
    await interaction.response.send_message(text[:1900], ephemeral=True)


# ================= لوحات (تذاكر + رتب) =================
@bot.tree.command(name="ticket_panel", description="إرسال لوحة فتح التذاكر")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def ticket_panel(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    embed = discord.Embed(
        title="🎫 الدعم الفني",
        description="محتاج مساعدة؟ دوس الزر تحت وتفتح تذكرة خاصة مع فريق الدعم.",
        color=discord.Color.blurple(),
    )
    await channel.send(embed=embed, view=TicketPanel())
    await interaction.response.send_message("✅ تم", ephemeral=True)


@bot.tree.command(name="role_panel", description="لوحة أزرار لأخذ الرتب")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.guild_only()
async def role_panel(
    interaction: discord.Interaction,
    title: str,
    role1: discord.Role,
    role2: discord.Role = None,
    role3: discord.Role = None,
    role4: discord.Role = None,
    role5: discord.Role = None,
):
    roles = [r for r in (role1, role2, role3, role4, role5) if r]
    for r in roles:
        if r.permissions.administrator or r.permissions.manage_guild or r.managed:
            return await interaction.response.send_message(
                f"❌ ما نقدرش نحط رتبة **{r.name}** في لوحة عامة (فيها صلاحيات إدارة)", ephemeral=True
            )
    view = discord.ui.View(timeout=None)
    for r in roles:
        view.add_item(RoleButton(r.id, r.name))
    embed = discord.Embed(title=title, description="دوس على الزر عشان تاخذ الرتبة أو تشيلها", color=discord.Color.blurple())
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ تم", ephemeral=True)


# ================= أوامر الأدمن =================
@bot.tree.command(name="announce", description="إرسال إعلان في روم معين")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    channel="الروم اللي يتبعت فيه الإعلان",
    title="عنوان الإعلان",
    message="نص الإعلان",
    mention_everyone="منشن @everyone؟",
)
async def announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    message: str,
    mention_everyone: bool = False,
):
    embed = discord.Embed(title=f"📢 {title}", description=message, color=discord.Color.gold())
    await channel.send(
        content="@everyone" if mention_everyone else None,
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=mention_everyone),
    )
    await interaction.response.send_message("✅ تم إرسال الإعلان", ephemeral=True)


@bot.tree.command(name="dm", description="إرسال رسالة في الخاص لعضو")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="العضو", text="الرسالة")
async def dm(interaction: discord.Interaction, member: discord.Member, text: str):
    try:
        await member.send(text)
        await interaction.response.send_message(f"✅ انبعتت لـ {member.mention}", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ الخاص مقفول عند العضو", ephemeral=True)


@bot.tree.command(name="say", description="خلي البوت يكتب رسالة في روم")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(channel="الروم (مثلاً الشات العام)", text="الكلام")
async def say(interaction: discord.Interaction, channel: discord.TextChannel, text: str):
    await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.send_message("✅ تم", ephemeral=True)


bot.run(TOKEN)
