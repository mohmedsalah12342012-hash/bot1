# -*- coding: utf-8 -*-
"""
GameBot - بوت إدارة السيرفر (متجر رتب + تذاكر + حماية + ترحيب + مسابقات)

طريقة البدء: اكتب كلمة  بداية  في أي روم (بدون ! أو /) ← اختر الروم ← اختر الخدمة.
"""

import discord
from discord import app_commands
from discord.ext import commands
import os
import re
import json
import time
import random
import asyncio
import traceback
import io
import unicodedata
from PIL import Image, ImageDraw, ImageFont, ImageFilter, features as pil_features
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

# ==================== الإعدادات والمفاتيح ====================
DISCORD_BOT_TOKEN = os.getenv("DISCORD_TOKEN")

OWNER_ID = 1511661628394049617      # صاحب البوت: صلاحيات كاملة حتى بدون Administrator
OWNER_NAME = "Rezo"
CONFIG_FILE = "server_config.json"
TICKET_CATEGORY = "🎫 التذاكر"
START_TEXT = "حسنًا، تم تفعيل البوت! لكن ماذا تريد أن يتفعل وفي أي روم؟"
START_WORDS = ("بداية", "بدايه")    # الكلمة التي تشغّل البوت بدون أي رمز
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(BASE_DIR, "welcome_template.png")   # قالب صورة الترحيب
FONT_PATH = os.path.join(BASE_DIR, "font.ttf")                   # خط يدعم العربي

# ==================== الرتب (10 رتب من الأقل إلى الأعلى) ====================
def fancy(text: str) -> str:
    """يحوّل الحروف الإنجليزية لخط فخم (Bold Italic Serif) مثل أسماء الرتب في الصورة."""
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(0x1D468 + ord(ch) - 65))
        elif "a" <= ch <= "z":
            out.append(chr(0x1D482 + ord(ch) - 97))
        else:
            out.append(ch)
    return "".join(out)


SERVER_TAG = "Rezo"           # الاسم الأول في كل رتبة (بدل ZIUO)
RANK_PRICE_START = 30000      # سعر أقل رتبة (عملة)
RANK_PRICE_STEP = 20000       # كل رتبة أغلى من اللي قبلها بـ 20 ألف

RANK_DEFS = [
    ("ROOKIE", "🌱", 0x99AAB5, ["نشر الـ GIF والصور والملفات في أي روم."],
     ["embed_links", "attach_files"]),
    ("PLAYER", "🎮", 0x2ECC71, ["استخدام إيموجي وستيكرز السيرفرات الأخرى."],
     ["use_external_emojis", "use_external_stickers"]),
    ("SKILLED", "⚔️", 0x1ABC9C, ["تغيير اسمك في السيرفر.", "إنشاء ثريدات (نقاشات فرعية)."],
     ["change_nickname", "create_public_threads", "create_private_threads", "send_messages_in_threads"]),
    ("ELITE", "💠", 0x3498DB, ["البث والفيديو والأنشطة في الرومات الصوتية.", "استخدام لوحة الأصوات (Soundboard)."],
     ["stream", "use_embedded_activities", "use_soundboard", "use_external_sounds"]),
    ("PRO", "🔥", 0x9B59B6, ["أولوية التحدث في الصوت.", "إرسال رسائل صوتية وإنشاء استفتاءات."],
     ["priority_speaker", "send_voice_messages", "send_polls"]),
    ("MVP", "⭐", 0xE91E63, ["إدارة الرسائل (حذف وتثبيت).", "إدارة الثريدات."],
     ["manage_messages", "manage_threads"]),
    ("VIP", "⚡", 0xE74C3C, ["كتم وتصميت ونقل الأعضاء في الرومات الصوتية."],
     ["mute_members", "deafen_members", "move_members"]),
    ("LEGEND", "👑", 0xE67E22, ["منشن @everyone و @here.", "إدارة ألقاب الأعضاء.", "إضافة وإدارة الإيموجي والستيكرز."],
     ["mention_everyone", "manage_nicknames", "manage_expressions", "create_expressions"]),
    ("MYTHIC", "🌌", 0xF1C40F, ["إسكات الأعضاء (Timeout) وطردهم.", "رؤية سجل التدقيق.", "إنشاء وإدارة الفعاليات."],
     ["moderate_members", "kick_members", "view_audit_log", "manage_events", "create_events"]),
    ("ULTIMATE", "💎", 0x00E5FF, ["كل الصلاحيات تقريباً: حظر الأعضاء، إدارة الرتب والسيرفر والويب هوك.",
                                  "ما عدا: صلاحية الأدمن، وإنشاء/إدارة الرومات."],
     None),
]


def rank_permissions(index: int) -> discord.Permissions:
    if RANK_DEFS[index][4] is None:
        perms = discord.Permissions.all()
        perms.administrator = False
        perms.manage_channels = False
        return perms
    perms = discord.Permissions.none()
    for i in range(index + 1):
        for name in (RANK_DEFS[i][4] or []):
            if hasattr(discord.Permissions, name):
                setattr(perms, name, True)
    return perms


RANKS = {}
for _i, (_name, _emoji, _color, _perks, _perm_names) in enumerate(RANK_DEFS, start=1):
    RANKS[f"r{_i}"] = {
        "index": _i, "short": _name, "emoji": _emoji, "color": discord.Color(_color),
        "price": RANK_PRICE_START + RANK_PRICE_STEP * (_i - 1),
        "perks": _perks,
        "role_name": f"{fancy(SERVER_TAG)} • {fancy(_name)} 「{_emoji}」",
    }
RANK_ROLE_NAMES = {r["role_name"] for r in RANKS.values()}

SECURITY_OPTIONS = {
    "anti_link": ("منع الروابط", "🔗"),
    "anti_spam": ("منع السبام", "💬"),
    "anti_mention": ("منع المنشن الجماعي", "📢"),
}

# ==================== حفظ وتحميل الإعدادات ====================
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(data=None):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(SERVER_DATA if data is None else data, f, ensure_ascii=False, indent=4)


SERVER_DATA = load_config()


def gcfg(guild_id):
    return SERVER_DATA.setdefault(str(guild_id), {})


# ==================== أدوات مساعدة ====================
OWNER_ROLE_KEYWORDS = ("owner", "اونر", "أونر")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def is_owner_role(role) -> bool:
    name = _norm(role.name)
    return any(k in name for k in OWNER_ROLE_KEYWORDS)


def is_staff(user) -> bool:
    if user.id == OWNER_ID:
        return True
    roles = getattr(user, "roles", None)
    return bool(roles and any(is_owner_role(r) for r in roles))


def is_exempt(member) -> bool:
    perms = getattr(member, "guild_permissions", None)
    return is_staff(member) or bool(perms and perms.administrator)


def missing_send_perms(channel):
    perms = channel.permissions_for(channel.guild.me)
    missing = []
    if not perms.view_channel:
        missing.append("عرض القناة")
    if not perms.send_messages:
        missing.append("إرسال الرسائل")
    if not perms.embed_links:
        missing.append("تضمين الروابط (Embed)")
    return missing


async def ensure_can_send(interaction, channel) -> bool:
    missing = missing_send_perms(channel)
    if missing:
        await interaction.followup.send(
            f"🚫 البوت لا يملك الصلاحيات التالية في {channel.mention}: **{'، '.join(missing)}**",
            ephemeral=True,
        )
        return False
    return True


async def report_error(interaction: discord.Interaction, error: Exception):
    traceback.print_exception(type(error), error, error.__traceback__)
    if isinstance(error, discord.Forbidden):
        text = "🚫 البوت لا يملك صلاحية كافية لتنفيذ ذلك. تأكد من صلاحياته ومن ترتيب رتبته في السيرفر."
    else:
        text = "⚠️ حدث خطأ غير متوقع أثناء التنفيذ، حاول مرة أخرى."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass


class SafeView(discord.ui.View):
    def __init__(self, timeout=None):
        super().__init__(timeout=timeout)

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


class StaffView(SafeView):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if is_staff(interaction.user):
            return True
        await interaction.response.send_message("🚫 التحكم بالبوت لأصحاب رتبة **Owner** فقط.", ephemeral=True)
        return False


# ==================== البوت ====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

BG_TASKS = set()


class GameBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(InitialChannelView())
        self.add_view(FeaturesView())
        for _action in PICK_PROMPTS:
            self.add_view(ChannelPickView(_action))
        self.add_view(ShopView())
        self.add_view(RankChoiceView())
        self.add_view(TicketPanelView())
        self.add_view(TicketControlView())
        self.add_view(GiveawayView())

        for gid, cfg in SERVER_DATA.items():
            for mid, data in cfg.get("giveaways", {}).items():
                if not data.get("ended"):
                    schedule_giveaway(int(gid), int(mid), data["end_ts"])

        try:
            synced = await self.tree.sync()
            print(f"🔄 تم مزامنة {len(synced)} أمر سلاش.")
        except Exception as e:
            print(f"⚠️ خطأ المزامنة: {e}")


bot = GameBot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ تم تشغيل البوت بنجاح باسم: {bot.user.name}")


# ==================== أمر البداية ====================
class InitialChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            custom_id="gb:init",
            placeholder="اختر الروم الذي تريد التفاعل والبدء فيه...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1, max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        target = interaction.guild.get_channel(self.values[0].id)
        if target is None:
            return await interaction.followup.send("⚠️ حدث خطأ في الوصول للروم المختار.", ephemeral=True)
        if not await ensure_can_send(interaction, target):
            return

        embed = discord.Embed(
            title="⚡ لوحة التحكم",
            description="**ماذا تريد أن نبدأ الآن؟**\nاختر النظام أو الخدمة المراد تفعيلها في هذا الروم من القائمة بالأسفل.",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"التحكم لأصحاب رتبة Owner فقط • {OWNER_NAME} Store")
        await target.send(embed=embed, view=FeaturesView())
        await interaction.followup.send(
            f"👌 ممتاز! تم الانتقال إلى الروم {target.mention} وبدء الخيارات هناك.", ephemeral=True
        )


class InitialChannelView(StaffView):
    def __init__(self):
        super().__init__()
        self.add_item(InitialChannelSelect())


# ==================== القائمة الشاملة للخدمات ====================
class FeaturesSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="نظام شراء الرتب", value="rank_shop", description="شراء رتبة • مميزات الرتب • تقديم إدارة", emoji="🏷️"),
            discord.SelectOption(label="نظام التذاكر (Tickets)", value="tickets", description="لوحة لفتح تذاكر الدعم الفني", emoji="🎫"),
            discord.SelectOption(label="معلومات وإحصائيات السيرفر", value="server_info", description="تفاصيل الأعضاء والرومات والرتب والبوست", emoji="📊"),
            discord.SelectOption(label="نظام الحماية والمنع", value="security", description="منع الروابط والسبام والمنشن الجماعي", emoji="🛡️"),
            discord.SelectOption(label="نظام الترحيب الآلي", value="welcome", description="رسالة ترحيب بكل عضو جديد", emoji="🎉"),
            discord.SelectOption(label="نظام المسابقات (Giveaways)", value="giveaway", description="مسابقة بزر مشاركة واختيار فائزين تلقائي", emoji="🎁"),
        ]
        super().__init__(custom_id="gb:features", placeholder="اختر الخدمة أو النظام الذي تريد البدء فيه...", options=options)

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        try:
            await self.handle(interaction, val)
        finally:
            try:
                await interaction.message.edit(view=FeaturesView())
            except discord.HTTPException:
                pass

    async def handle(self, interaction: discord.Interaction, val: str):
        if val == "security":
            return await interaction.response.send_message(
                embed=security_embed(interaction.guild_id),
                view=SecurityView(interaction.guild_id), ephemeral=True,
            )
        await interaction.response.send_message(PICK_PROMPTS[val], view=ChannelPickView(val), ephemeral=True)


class FeaturesView(StaffView):
    def __init__(self):
        super().__init__()
        self.add_item(FeaturesSelect())


# ==================== اختيار الروم لكل خدمة ====================
PICK_PROMPTS = {
    "rank_shop": "🏷️ اختر الروم الذي تريد نشر **متجر الرتب** فيه (سيتم إنشاء الـ10 رتب تلقائياً):",
    "tickets": "🎫 اختر الروم الذي تريد نشر **لوحة التذاكر** فيه:",
    "server_info": "📊 اختر الروم الذي تريد إرسال **إحصائيات السيرفر** فيه:",
    "welcome": "🎉 اختر الروم الذي تريد **الترحيب بالأعضاء الجدد** فيه:",
    "giveaway": "🎁 اختر الروم الذي تريد إقامة **المسابقة** فيه:",
}


class ChannelPickSelect(discord.ui.ChannelSelect):
    def __init__(self, action: str):
        super().__init__(
            custom_id=f"gb:pick:{action}",
            placeholder="اختر الروم...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1, max_values=1,
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(self.values[0].id)
        if channel is None:
            return await interaction.response.send_message("⚠️ تعذر إيجاد هذه القناة!", ephemeral=True)
        if self.action == "giveaway":
            return await interaction.response.send_modal(GiveawayModal(channel))
        await interaction.response.defer(ephemeral=True)
        if not await ensure_can_send(interaction, channel):
            return
        await run_action(interaction, self.action, channel)


class ChannelPickView(StaffView):
    def __init__(self, action: str):
        super().__init__()
        self.add_item(ChannelPickSelect(action))


async def run_action(interaction: discord.Interaction, action: str, channel: discord.TextChannel):
    guild = interaction.guild
    cfg = gcfg(guild.id)

    if action == "rank_shop":
        note = ""
        try:
            created, limited = await ensure_rank_roles(guild)
            if created:
                note += f"\n🆕 تم إنشاء {len(created)} رتبة."
            if limited:
                note += "\n⚠️ بعض صلاحيات الرتب العليا لم تُمنح لأن البوت نفسه لا يملكها (أعطِ البوت Administrator ثم احذف الرتب لتُنشأ من جديد)."
        except discord.Forbidden:
            note = "\n⚠️ لم أستطع إنشاء الرتب: أعطِ البوت صلاحية **Manage Roles** وضع رتبته فوق رتب المتجر."
        await channel.send(embed=build_shop_embed(), view=ShopView())
        await interaction.followup.send(f"✅ تم نشر متجر الرتب في {channel.mention}!{note}", ephemeral=True)

    elif action == "tickets":
        embed = discord.Embed(
            title="🎫 **نظام التذاكر والدعم الفني**",
            description="إذا كان لديك أي استفسار أو مشكلة، اضغط على الزر بالأسفل لفتح تذكرة خاصة مع الإدارة.\n"
                        "ستظهر التذكرة لك وللإدارة فقط.",
            color=discord.Color.blue(),
        )
        await channel.send(embed=embed, view=TicketPanelView())
        await interaction.followup.send(f"✅ تم إنشاء لوحة التذاكر في {channel.mention}!", ephemeral=True)

    elif action == "server_info":
        await channel.send(embed=build_server_info(guild))
        await interaction.followup.send(f"✅ تم إرسال إحصائيات السيرفر في {channel.mention}!", ephemeral=True)

    elif action == "welcome":
        cfg["welcome_channel"] = channel.id
        save_config()
        content, file = await build_welcome_message(interaction.user)
        await channel.send(content=content, file=file) if file else await channel.send(content=content)
        await interaction.followup.send(f"✅ تم ضبط روم الترحيب على {channel.mention}.", ephemeral=True)


# ==================== إحصائيات السيرفر ====================
def build_server_info(guild: discord.Guild) -> discord.Embed:
    embed = discord.Embed(title=f"📊 إحصائيات سيرفر {guild.name}", color=discord.Color.green())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    bots = sum(1 for m in guild.members if m.bot)
    embed.add_field(name="👑 المالك", value=guild.owner.mention if guild.owner else "غير معروف", inline=True)
    embed.add_field(name="📅 تاريخ الإنشاء", value=discord.utils.format_dt(guild.created_at, "D"), inline=True)
    embed.add_field(name="👥 الأعضاء", value=f"{guild.member_count} (بوتات: {bots})", inline=True)
    embed.add_field(name="💬 رومات كتابية", value=str(len(guild.text_channels)), inline=True)
    embed.add_field(name="🔊 رومات صوتية", value=str(len(guild.voice_channels)), inline=True)
    embed.add_field(name="🏷️ الرتب", value=str(len(guild.roles) - 1), inline=True)
    embed.add_field(name="😀 الإيموجي", value=str(len(guild.emojis)), inline=True)
    embed.add_field(name="🚀 البوست", value=f"مستوى {guild.premium_tier} ({guild.premium_subscription_count} بوست)", inline=True)
    embed.add_field(name="🔒 مستوى التحقق", value=str(guild.verification_level).capitalize(), inline=True)
    embed.set_footer(text=f"{OWNER_NAME} Store")
    return embed


# ==================== متجر الرتب ====================
def price_text(r: dict) -> str:
    return f"🪙 {r['price']:,} عملة"


async def ensure_rank_roles(guild: discord.Guild):
    me = guild.me
    if not me.guild_permissions.manage_roles:
        raise discord.Forbidden(type("R", (), {"status": 403, "reason": "no manage_roles"})(), "Missing Manage Roles")
    created, limited = [], False
    for key in reversed(list(RANKS)):
        r = RANKS[key]
        if discord.utils.get(guild.roles, name=r["role_name"]):
            continue
        wanted = rank_permissions(r["index"] - 1)
        perms = wanted
        if not me.guild_permissions.administrator:
            perms = discord.Permissions(wanted.value & me.guild_permissions.value)
            limited = limited or perms.value != wanted.value
        await guild.create_role(
            name=r["role_name"], color=r["color"], permissions=perms, hoist=True,
            reason="إنشاء رتب المتجر تلقائياً",
        )
        created.append(r["short"])
        await asyncio.sleep(0.6)
    return created, limited


def build_shop_embed() -> discord.Embed:
    first, last = RANKS["r1"], RANKS[f"r{len(RANKS)}"]
    embed = discord.Embed(
        title="🏷️ متجر الرتب الرسمي",
        description=(
            "اختر من الأزرار بالأسفل:\n\n"
            "🛒 **شراء رتبة** — اختر الرتبة واكتب السبب لفتح تذكرة شراء.\n"
            "📜 **عرض مميزات الرتب** — تفاصيل الـ10 رتب وأسعارها.\n"
            "📝 **تقديم إدارة** — قدّم طلبك للانضمام لفريق الإدارة.\n\n"
            f"{price_text(first)} ← {price_text(last)}"
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text=f"{OWNER_NAME} Store")
    return embed


def perks_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📜 مميزات الرتب",
        description="الرتب مرتبة من الأقل للأعلى. كل رتبة تحصل على **كل مميزات الرتب السابقة** + الجديد.",
        color=discord.Color.gold(),
    )
    for r in RANKS.values():
        prefix = "" if r["index"] == 1 else "✅ كل مميزات الرتب السابقة\n"
        embed.add_field(
            name=f"{r['emoji']} {r['index']}. {r['short']} — {price_text(r)}",
            value=prefix + "\n".join(f"• {p}" for p in r["perks"]),
            inline=False,
        )
    embed.set_footer(text=f"{OWNER_NAME} Store")
    return embed


class RankReasonModal(discord.ui.Modal):
    def __init__(self, key: str):
        r = RANKS[key]
        super().__init__(title=f"شراء رتبة {r['short']} {r['emoji']}"[:45])
        self.key = key
        self.reason = discord.ui.TextInput(
            label="سبب شراء الرتبة", style=discord.TextStyle.paragraph,
            placeholder="اكتب سبب رغبتك في شراء هذه الرتبة...", min_length=3, max_length=400, required=True,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await create_ticket(interaction, self.key, reason=self.reason.value)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await report_error(interaction, error)


class RankChoiceSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=f"{r['index']}. {r['short']}", value=key,
                                 description=f"{r['price']:,} عملة", emoji=r["emoji"])
            for key, r in RANKS.items()
        ]
        super().__init__(custom_id="gb:shop:choose", placeholder="اختر الرتبة التي تريد شراءها...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RankReasonModal(self.values[0]))


class RankChoiceView(SafeView):
    def __init__(self):
        super().__init__()
        self.add_item(RankChoiceSelect())


class ShopView(SafeView):
    @discord.ui.button(label="شراء رتبة", emoji="🛒", style=discord.ButtonStyle.success, custom_id="gb:shop:buy")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🛒 اختر الرتبة التي تريد شراءها:", view=RankChoiceView(), ephemeral=True)

    @discord.ui.button(label="عرض مميزات الرتب", emoji="📜", style=discord.ButtonStyle.primary, custom_id="gb:shop:perks")
    async def perks(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=perks_embed(), ephemeral=True)

    @discord.ui.button(label="تقديم إدارة", emoji="📝", style=discord.ButtonStyle.secondary, custom_id="gb:shop:apply")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction, "apply")


# ==================== نظام التذاكر ====================
def parse_ticket(channel):
    topic = getattr(channel, "topic", None) or ""
    if not topic.startswith("gb-ticket|"):
        return None
    try:
        _, uid, kind = topic.split("|", 2)
        return int(uid), kind
    except ValueError:
        return None


async def create_ticket(interaction: discord.Interaction, kind: str = "support", reason: str = None):
    await interaction.response.defer(ephemeral=True)
    guild, user, me = interaction.guild, interaction.user, interaction.guild.me

    for ch in guild.text_channels:
        if (ch.topic or "").startswith(f"gb-ticket|{user.id}|"):
            return await interaction.followup.send(f"📌 لديك تذكرة مفتوحة بالفعل: {ch.mention}", ephemeral=True)

    if not me.guild_permissions.manage_channels:
        return await interaction.followup.send("🚫 البوت يحتاج صلاحية **إدارة القنوات (Manage Channels)** لفتح التذاكر.", ephemeral=True)

    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY)
    if category is None:
        category = await guild.create_category(
            TICKET_CATEGORY,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            },
        )

    member_perms = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: member_perms,
        me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True, embed_links=True),
    }
    owner = guild.get_member(OWNER_ID)
    if owner:
        overwrites[owner] = member_perms
    for role in guild.roles:
        if role != guild.default_role and is_owner_role(role):
            overwrites[role] = member_perms

    channel = await guild.create_text_channel(
        name=f"ticket-{user.name}"[:90],
        category=category,
        overwrites=overwrites,
        topic=f"gb-ticket|{user.id}|{kind}",
        reason=f"تذكرة جديدة من {user}",
    )

    if kind in RANKS:
        r = RANKS[kind]
        embed = discord.Embed(
            title=f"🛒 طلب شراء رتبة {r['short']} {r['emoji']}",
            description=f"أهلاً {user.mention}!\n"
                        f"سيتواصل معك **{OWNER_NAME}** هنا لتأكيد الدفع، وبعدها يتم تفعيل الرتبة فوراً.",
            color=r["color"],
        )
        embed.add_field(name="🏷️ الرتبة", value=f"{r['index']}. {r['short']}", inline=True)
        embed.add_field(name="💰 السعر", value=price_text(r), inline=True)
        embed.add_field(name="📝 السبب", value=(reason or "—")[:1000], inline=False)
        embed.add_field(name="✨ المميزات", value="\n".join(f"• {p}" for p in r["perks"]), inline=False)
    elif kind == "apply":
        embed = discord.Embed(
            title="📝 تقديم إدارة",
            description=f"أهلاً {user.mention}!\nاكتب هنا المعلومات التالية وسيراجع طلبك الأونر:\n\n"
                        "1️⃣ عمرك\n2️⃣ خبرتك في الإدارة\n3️⃣ لماذا تريد الانضمام لفريق الإدارة؟\n4️⃣ كم ساعة تتواجد يومياً؟",
            color=discord.Color.dark_gold(),
        )
    else:
        embed = discord.Embed(
            title="🎫 تذكرة دعم فني",
            description=f"أهلاً {user.mention}!\nاشرح مشكلتك أو استفسارك هنا وسيرد عليك أحد الإداريين قريباً.",
            color=discord.Color.blue(),
        )
    embed.set_footer(text="اضغط 🔒 لإغلاق التذكرة عند الانتهاء")
    ping = f"{user.mention} {owner.mention}" if owner else user.mention
    await channel.send(content=ping, embed=embed, view=TicketControlView())

    if owner and kind in RANKS:
        try:
            await owner.send(f"🛒 طلب شراء رتبة **{RANKS[kind]['short']}** ({price_text(RANKS[kind])}) من **{user}** في سيرفر **{guild.name}**: {channel.mention}")
        except discord.HTTPException:
            pass
    elif owner and kind == "apply":
        try:
            await owner.send(f"📝 طلب تقديم إدارة من **{user}** في سيرفر **{guild.name}**: {channel.mention}")
        except discord.HTTPException:
            pass

    await interaction.followup.send(f"✅ تم فتح تذكرتك: {channel.mention}", ephemeral=True)


class TicketPanelView(SafeView):
    @discord.ui.button(label="فتح تذكرة", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="gb:ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await create_ticket(interaction, "support")


class TicketControlView(SafeView):
    @discord.ui.button(label="تفعيل الرتبة", emoji="✅", style=discord.ButtonStyle.success, custom_id="gb:ticket:grant")
    async def grant(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("🚫 هذا الزر لأصحاب رتبة **Owner** فقط.", ephemeral=True)
        info = parse_ticket(interaction.channel)
        if not info or info[1] not in RANKS:
            return await interaction.response.send_message("ℹ️ هذه ليست تذكرة شراء رتبة.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        uid, kind = info
        guild = interaction.guild
        member = guild.get_member(uid)
        if member is None:
            try:
                member = await guild.fetch_member(uid)
            except discord.NotFound:
                return await interaction.followup.send("⚠️ العضو غير موجود في السيرفر.", ephemeral=True)

        r = RANKS[kind]
        await ensure_rank_roles(guild)
        role = discord.utils.get(guild.roles, name=r["role_name"])
        if role is None:
            return await interaction.followup.send("⚠️ تعذر إيجاد الرتبة، تأكد من صلاحيات البوت.", ephemeral=True)
        old = [x for x in member.roles if x.name in RANK_ROLE_NAMES and x.id != role.id]
        if old:
            await member.remove_roles(*old, reason="ترقية رتبة")
        await member.add_roles(role, reason=f"تفعيل رتبة بواسطة {interaction.user}")

        await interaction.channel.send(f"🎉 تم تفعيل رتبة {role.mention} للعضو {member.mention} بنجاح! شكراً لدعمك 💛")
        await interaction.followup.send("✅ تم تفعيل الرتبة.", ephemeral=True)

    @discord.ui.button(label="إغلاق التذكرة", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="gb:ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        info = parse_ticket(interaction.channel)
        if not info:
            return await interaction.response.send_message("ℹ️ هذه ليست تذكرة.", ephemeral=True)
        if not (is_staff(interaction.user) or interaction.user.id == info[0]):
            return await interaction.response.send_message("🚫 لا يمكنك إغلاق هذه التذكرة.", ephemeral=True)
        await interaction.response.send_message("🔒 سيتم إغلاق التذكرة وحذفها خلال 5 ثوانٍ...")
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"أغلقها {interaction.user}")


# ==================== نظام الحماية ====================
URL_RE = re.compile(r"(https?://|www\.|discord\.gg/|discord(app)?\.com/invite/)", re.I)
SPAM_LOG = defaultdict(deque)


def security_embed(guild_id) -> discord.Embed:
    cfg = gcfg(guild_id)
    lines = [f"{emoji} **{label}:** {'✅ مفعّل' if cfg.get(key) else '❌ معطّل'}" for key, (label, emoji) in SECURITY_OPTIONS.items()]
    embed = discord.Embed(title="🛡️ نظام الحماية والمنع", description="اضغط على الزر لتفعيل/تعطيل الخاصية.\n(الأونر والأدمن مستثنون من كل القيود)\n\n" + "\n".join(lines), color=discord.Color.dark_red())
    return embed


class SecurityToggle(discord.ui.Button):
    def __init__(self, key: str, enabled: bool):
        label, emoji = SECURITY_OPTIONS[key]
        super().__init__(
            label=f"{label}: {'مفعّل' if enabled else 'معطّل'}", emoji=emoji,
            style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
        )
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        cfg = gcfg(interaction.guild_id)
        cfg[self.key] = not cfg.get(self.key, False)
        save_config()
        await interaction.response.edit_message(embed=security_embed(interaction.guild_id), view=SecurityView(interaction.guild_id))


class SecurityView(StaffView):
    def __init__(self, guild_id):
        super().__init__(timeout=900)
        cfg = gcfg(guild_id)
        for key in SECURITY_OPTIONS:
            self.add_item(SecurityToggle(key, cfg.get(key, False)))


async def run_security(message: discord.Message) -> bool:
    cfg = gcfg(message.guild.id)
    if not any(cfg.get(k) for k in SECURITY_OPTIONS) or is_exempt(message.author):
        return False

    content = message.content
    reason = None
    if cfg.get("anti_link") and URL_RE.search(content):
        reason = f"⚠️ يمنع إرسال الروابط هنا يا {message.author.mention}!"
    elif cfg.get("anti_mention") and (message.mention_everyone or len(message.mentions) >= 5):
        reason = f"⚠️ يمنع المنشن الجماعي يا {message.author.mention}!"
    elif cfg.get("anti_spam"):
        now = time.monotonic()
        log = SPAM_LOG[(message.guild.id, message.author.id)]
        log.append(now)
        while log and now - log[0] > 6:
            log.popleft()
        if len(log) >= 6:
            log.clear()
            try:
                await message.author.timeout(timedelta(minutes=1), reason="سبام")
            except discord.HTTPException:
                pass
            reason = f"⚠️ توقف عن السبام يا {message.author.mention}! تم كتمك دقيقة."

    if reason:
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            await message.channel.send(reason, delete_after=6)
        except discord.HTTPException:
            pass
        return True
    return False


# ==================== الترحيب (صورة مخصصة) ====================
AV_CENTER, AV_RADIUS = (967, 299), 194
NAME_CENTER, NAME_MAX_W = (967, 531), 700

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:
    arabic_reshaper = get_display = None
HAS_RAQM = pil_features.check("raqm")


def _font(size: int):
    for path in (FONT_PATH, "DejaVuSans-Bold.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default(size)


def _shape(text: str) -> str:
    has_ar = any("\u0600" <= c <= "\u06ff" for c in text)
    if has_ar and not HAS_RAQM and arabic_reshaper and get_display:
        return get_display(arabic_reshaper.reshape(text))
    return text


def _fallback_template() -> Image.Image:
    img = Image.new("RGBA", (1942, 809), (4, 8, 24, 255))
    d = ImageDraw.Draw(img)
    cx, cy = AV_CENTER
    d.ellipse((cx - 205, cy - 205, cx + 205, cy + 205), outline=(40, 160, 255, 255), width=10)
    d.rounded_rectangle((520, 470, 1420, 565), radius=20, outline=(40, 160, 255, 255), width=4)
    return img


def make_welcome_card(avatar_bytes: bytes, name: str) -> io.BytesIO:
    card = Image.open(TEMPLATE_PATH).convert("RGBA") if os.path.exists(TEMPLATE_PATH) else _fallback_template()

    size = AV_RADIUS * 2
    avatar = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
    scale = 4
    mask = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * scale - 1, size * scale - 1), fill=255)
    mask = mask.resize((size, size), Image.LANCZOS)
    card.paste(avatar, (AV_CENTER[0] - AV_RADIUS, AV_CENTER[1] - AV_RADIUS), mask)

    text = _shape(name.strip()[:24] or "Member")
    draw = ImageDraw.Draw(card)
    fs = 54
    font = _font(fs)
    while fs > 20 and draw.textlength(text, font=font) > NAME_MAX_W:
        fs -= 2
        font = _font(fs)
    glow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text(NAME_CENTER, text, font=font, fill=(40, 160, 255, 255), anchor="mm",
                              stroke_width=6, stroke_fill=(40, 160, 255, 255))
    card = Image.alpha_composite(card, glow.filter(ImageFilter.GaussianBlur(9)))
    ImageDraw.Draw(card).text(NAME_CENTER, text, font=font, fill=(255, 255, 255, 255), anchor="mm",
                              stroke_width=3, stroke_fill=(0, 20, 70, 255))

    out = io.BytesIO()
    card.convert("RGB").save(out, "JPEG", quality=93)
    out.seek(0)
    return out


async def build_welcome_message(member):
    guild = getattr(member, "guild", None)
    count = guild.member_count if guild else "؟"
    content = f"أهلاً يا جميل\nأنت العضو رقم {count}"
    try:
        avatar_bytes = await member.display_avatar.replace(size=512, format="png").read()
        loop = asyncio.get_running_loop()
        buf = await loop.run_in_executor(None, make_welcome_card, avatar_bytes, member.display_name)
        return content, discord.File(buf, filename="welcome.jpg")
    except Exception:
        traceback.print_exc()
        return content, None


@bot.event
async def on_member_join(member: discord.Member):
    cid = gcfg(member.guild.id).get("welcome_channel")
    channel = member.guild.get_channel(cid) if cid else None
    if channel is None:
        return
    content, file = await build_welcome_message(member)
    try:
        if file:
            await channel.send(content=content, file=file)
        else:
            await channel.send(content=content)
    except discord.HTTPException:
        pass


# ==================== المسابقات ====================
def giveaway_embed(data: dict, ended: bool = False) -> discord.Embed:
    end_dt = datetime.fromtimestamp(data["end_ts"], tz=timezone.utc)
    embed = discord.Embed(title=f"🎁 مسابقة: {data['prize']}", color=discord.Color.dark_grey() if ended else discord.Color.gold())
    if ended:
        winners = data.get("winner_ids", [])
        embed.description = ("🏆 **الفائزون:** " + "، ".join(f"<@{w}>" for w in winners)) if winners else "😕 لم يشارك أحد في المسابقة."
    else:
        embed.description = f"اضغط على الزر بالأسفل للمشاركة!\n\n⏰ **تنتهي:** {discord.utils.format_dt(end_dt, 'R')}"
    embed.add_field(name="👤 المنظّم", value=f"<@{data['host_id']}>", inline=True)
    embed.add_field(name="🏆 عدد الفائزين", value=str(data["winners"]), inline=True)
    embed.add_field(name="👥 المشاركون", value=str(len(data["participants"])), inline=True)
    return embed


class GiveawayView(SafeView):
    def __init__(self, disabled: bool = False):
        super().__init__()
        for child in self.children:
            child.disabled = disabled

    @discord.ui.button(label="شارك", emoji="🎉", style=discord.ButtonStyle.primary, custom_id="gb:giveaway:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = gcfg(interaction.guild_id).get("giveaways", {}).get(str(interaction.message.id))
        if not data or data.get("ended"):
            return await interaction.response.send_message("⌛ انتهت هذه المسابقة.", ephemeral=True)
        uid = interaction.user.id
        if uid in data["participants"]:
            data["participants"].remove(uid)
            note = "↩️ تم إلغاء مشاركتك."
        else:
            data["participants"].append(uid)
            note = "✅ تم تسجيل مشاركتك! حظاً موفقاً 🍀"
        save_config()
        await interaction.response.edit_message(embed=giveaway_embed(data))
        await interaction.followup.send(note, ephemeral=True)


class GiveawayModal(discord.ui.Modal, title="🎁 إنشاء مسابقة جديدة"):
    prize = discord.ui.TextInput(label="الجائزة", placeholder="مثال: رتبة VIP", max_length=100)
    minutes = discord.ui.TextInput(label="المدة بالدقائق (1 - 10080)", default="60", max_length=5)
    winners = discord.ui.TextInput(label="عدد الفائزين (1 - 20)", default="1", max_length=2)

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            minutes, winners = int(self.minutes.value), int(self.winners.value)
        except ValueError:
            return await interaction.response.send_message("⚠️ المدة وعدد الفائزين يجب أن يكونا أرقاماً.", ephemeral=True)
        if not (1 <= minutes <= 10080) or not (1 <= winners <= 20):
            return await interaction.response.send_message("⚠️ المدة من 1 إلى 10080 دقيقة، والفائزون من 1 إلى 20.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        if not await ensure_can_send(interaction, self.channel):
            return

        data = {
            "channel_id": self.channel.id, "prize": self.prize.value.strip(),
            "end_ts": time.time() + minutes * 60, "winners": winners,
            "host_id": interaction.user.id, "participants": [], "ended": False,
        }
        msg = await self.channel.send(embed=giveaway_embed(data), view=GiveawayView())
        gcfg(interaction.guild_id).setdefault("giveaways", {})[str(msg.id)] = data
        save_config()
        schedule_giveaway(interaction.guild_id, msg.id, data["end_ts"])
        await interaction.followup.send("✅ تم إطلاق المسابقة بنجاح!", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await report_error(interaction, error)


async def finish_giveaway(guild_id: int, msg_id: int):
    data = gcfg(guild_id).get("giveaways", {}).get(str(msg_id))
    if not data or data.get("ended"):
        return
    data["ended"] = True
    guild = bot.get_guild(guild_id)
    pool = [u for u in data["participants"] if guild and guild.get_member(u)] or list(data["participants"])
    data["winner_ids"] = random.sample(pool, min(len(pool), data["winners"]))
    save_config()

    channel = guild.get_channel(data["channel_id"]) if guild else None
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(msg_id)
        await msg.edit(embed=giveaway_embed(data, ended=True), view=GiveawayView(disabled=True))
    except discord.HTTPException:
        pass
    if data["winner_ids"]:
        mentions = " ".join(f"<@{w}>" for w in data["winner_ids"])
        await channel.send(f"🎊 مبروك {mentions}! لقد ربحتم **{data['prize']}** 🎁\nتواصلوا مع <@{data['host_id']}> لاستلام الجائزة.")
    else:
        await channel.send(f"😕 انتهت مسابقة **{data['prize']}** بدون مشاركين.")


def schedule_giveaway(guild_id: int, msg_id: int, end_ts: float):
    async def runner():
        try:
            await bot.wait_until_ready()
            delay = end_ts - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            await finish_giveaway(guild_id, msg_id)
        except Exception:
            traceback.print_exc()

    task = asyncio.create_task(runner())
    BG_TASKS.add(task)
    task.add_done_callback(BG_TASKS.discard)


# ==================== استقبال الرسائل ====================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    content = message.content.strip()

    if content in START_WORDS:
        if not is_staff(message.author):
            await message.reply("🚫 التحكم بالبوت لأصحاب رتبة **Owner** فقط.", delete_after=6)
            return
        await message.channel.send(START_TEXT, view=InitialChannelView())
        return

    if await run_security(message):
        return


@bot.tree.command(name="بداية", description="تفعيل البوت واختيار الروم لبدء الأوامر والخدمات")
@app_commands.guild_only()
async def start_slash_command(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        return await interaction.response.send_message("🚫 التحكم بالبوت لأصحاب رتبة **Owner** فقط.", ephemeral=True)
    await interaction.response.send_message(START_TEXT, view=InitialChannelView())


# ==================== تشغيل البوت ====================
bot.run(DISCORD_BOT_TOKEN)