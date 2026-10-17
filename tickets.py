import io
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from db import db, get_settings, set_setting
from utils import embed, OK, ERR, set_image, apply_image


class OpenTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="فتح تذكرة", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="ticket:open")
    async def open(self, i: discord.Interaction, _):
        s = await get_settings(i.guild_id)
        old = await db.tickets.find_one({"gid": i.guild_id, "uid": i.user.id, "open": True})
        if old and i.guild.get_channel(old["channel"]):
            return await i.response.send_message(f"❌ عندك تذكرة مفتوحة: <#{old['channel']}>", ephemeral=True)

        category = i.guild.get_channel(s["ticket_category"]) if s.get("ticket_category") else None
        support = i.guild.get_role(s["ticket_role"]) if s.get("ticket_role") else None
        ow = {
            i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
            i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if support:
            ow[support] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        ch = await i.guild.create_text_channel(f"ticket-{i.user.name}", category=category, overwrites=ow, topic=str(i.user.id))
        await db.tickets.insert_one({"gid": i.guild_id, "uid": i.user.id, "channel": ch.id, "open": True,
                                     "ts": datetime.now(timezone.utc)})
        e = embed("🎫 تذكرة جديدة", f"أهلاً {i.user.mention}، اكتب مشكلتك وفريق الدعم بيرد عليك قريباً.")
        await ch.send(f"{i.user.mention} {support.mention if support else ''}", embed=e, view=CloseTicket())
        await i.response.send_message(f"✅ تم فتح تذكرتك: {ch.mention}", ephemeral=True)


class CloseTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="إغلاق التذكرة", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket:close")
    async def close(self, i: discord.Interaction, _):
        s = await get_settings(i.guild_id)
        owner_id = int(i.channel.topic) if i.channel.topic and i.channel.topic.isdigit() else 0
        support_id = s.get("ticket_role")
        allowed = (
            i.user.id == owner_id
            or i.user.guild_permissions.manage_channels
            or (support_id and any(r.id == support_id for r in i.user.roles))
        )
        if not allowed:
            return await i.response.send_message("❌ ما تقدر تغلق هذي التذكرة.", ephemeral=True)

        await i.response.send_message("🔒 جاري الإغلاق وحفظ السجل...")
        lines = []
        async for m in i.channel.history(limit=None, oldest_first=True):
            lines.append(f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author}: {m.content}")
        data = io.BytesIO("\n".join(lines).encode("utf-8"))
        if log_id := s.get("ticket_logs"):
            log = i.guild.get_channel(log_id)
            if log:
                await log.send(embed=embed("📁 تذكرة مغلقة", f"{i.channel.name}\nأغلقها: {i.user.mention}"),
                               file=discord.File(data, filename=f"{i.channel.name}.txt"))
        await db.tickets.update_one({"channel": i.channel.id}, {"$set": {"open": False}})
        await i.channel.delete(reason=f"Ticket closed by {i.user}")


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(OpenTicket())
        self.bot.add_view(CloseTicket())

    ticket = app_commands.Group(
        name="ticket", description="نظام التذاكر",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @ticket.command(name="setup", description="إنشاء لوحة التذاكر (مع صورة اختيارية)")
    @app_commands.describe(panel_channel="الروم اللي تنزل فيه اللوحة", category="كاتيجوري التذاكر",
                           support_role="رتبة الدعم", logs_channel="روم سجل التذاكر",
                           title="عنوان اللوحة", description="نص اللوحة",
                           image="ارفع صورة للوحة", image_url="أو رابط صورة مباشر")
    async def setup_ticket(self, i: discord.Interaction, panel_channel: discord.TextChannel,
                           category: discord.CategoryChannel, support_role: discord.Role,
                           logs_channel: discord.TextChannel | None = None,
                           title: str = "🎫 الدعم الفني",
                           description: str = "تحتاج مساعدة؟ اضغط الزر تحت لفتح تذكرة خاصة.",
                           image: discord.Attachment | None = None, image_url: str | None = None):
        await i.response.defer(ephemeral=True)
        if err := await set_image(i.guild_id, "ticket", image, image_url):
            return await i.followup.send(err, ephemeral=True)
        data = {"ticket_category": category.id, "ticket_role": support_role.id}
        if logs_channel:
            data["ticket_logs"] = logs_channel.id
        await set_setting(i.guild_id, **data)
        s = await get_settings(i.guild_id)
        e = embed(title, description.replace("\\n", "\n"))
        file = await apply_image(i.guild_id, "ticket", e, s)
        await panel_channel.send(embed=e, view=OpenTicket(), file=file)
        await i.followup.send(embed=embed("✅ تم", f"اللوحة نزلت في {panel_channel.mention}", OK), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tickets(bot))
