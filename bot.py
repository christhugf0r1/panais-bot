import os
import io
import re
import datetime

import discord
from discord.ext import commands, tasks
import pytesseract
from PIL import Image

# =========================
# ΡΥΘΜΙΣΕΙΣ BOT / RENDER
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")   # ΠΑΙΡΝΕΙ ΤΟ TOKEN ΑΠΟ ΤΟ ENV
PROOF_CHANNEL_ID = 1433200267947671604       # Κανάλι αποδείξεων
PAYMENTS_CHANNEL_ID = 1433226571501535282    # Κανάλι πληρωμών

# Tesseract (στο Render είναι Linux, άστο None και θα χρησιμοποιήσει system)
TESSERACT_PATH = None
if TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# Ρόλοι & ποσοστά
ROLE_PERCENTAGES = {
    "Original Boss": 0.30,
    "Vice Boss": 0.25,
    "Manager": 0.20,
    "Worker": 0.15,
    "Delivery": 0.10,
}

# Απλό storage στη RAM (χάνεται αν γίνει restart το bot, αλλά ΟΚ για τώρα)
# { "user_id": total_amount }
weekly_totals = {}

# =========================
# INTENTS & BOT
# =========================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# OCR ΒΟΗΘΗΤΙΚΑ
# =========================

def extract_numbers_from_image(image_bytes: bytes) -> int:
    """Κάνει OCR στην εικόνα (βελτιωμένο για GTA screenshots)."""
    try:
        img = Image.open(io.BytesIO(image_bytes))

        # --- PRE-PROCESSING IMPROVEMENTS ---
        # Convert to grayscale
        img = img.convert("L")

        # Increase contrast
        img = Image.eval(img, lambda x: 255 if x > 150 else 0)

        # Slight sharpen / upscale
        img = img.resize((img.width * 2, img.height * 2))

        # --- OCR with special settings ---
        text = pytesseract.image_to_string(
            img,
            lang="eng",
            config="--psm 6"
        )

        # Try to capture numbers with currency symbols
        matches = re.findall(r"(\d{2,6})", text)

        if not matches:
            print("OCR TEXT:", text)
            return 0

        # Add all detected numbers
        return sum(map(int, matches))

    except Exception as e:
        print("OCR ERROR:", e)
        return 0



def get_role_multiplier(member: discord.Member) -> float:
    """Βρίσκει ποσοστό ανάλογα με τον ρόλο του χρήστη."""
    if not member:
        return 0.0
    # Αν έχει παραπάνω από 1 από τους ρόλους μας, παίρνει το μεγαλύτερο ποσοστό
    max_mult = 0.0
    for role in member.roles:
        if role.name in ROLE_PERCENTAGES:
            mult = ROLE_PERCENTAGES[role.name]
            if mult > max_mult:
                max_mult = mult
    return max_mult


# =========================
# EVENTS
# =========================

@bot.event
async def on_ready():
    print(f"✅ Bot συνδέθηκε ως {bot.user}")
    weekly_payroll.start()


@bot.event
async def on_message(message: discord.Message):
    # Χρειαζόμαστε αυτό για να δουλεύουν τα commands
    await bot.process_commands(message)

    # Αγνόησε bots
    if message.author.bot:
        return

    # Θέλουμε μόνο το κανάλι PROOF
    if message.channel.id != PROOF_CHANNEL_ID:
        return

    if not message.attachments:
        return

    user_id = str(message.author.id)

    for attachment in message.attachments:
        # Μόνο εικόνες
        if not any(attachment.filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            continue

        data = await attachment.read()
        value = extract_numbers_from_image(data)

        if value <= 0:
            await message.channel.send(
                f"{message.author.mention} ❕ Δεν βρήκα έγκυρους αριθμούς στην απόδειξη."
            )
            continue

        # Πρόσθεσε στο εβδομαδιαίο σύνολο
        weekly_totals[user_id] = weekly_totals.get(user_id, 0) + value

        await message.channel.send(
            f"🧾 {message.author.mention} βρήκα σύνολο **{value}** από την απόδειξη.\n"
            f"📊 Τρέχον εβδομαδιαίο σύνολο σου: **{weekly_totals[user_id]}**."
        )


# =========================
# WEEKLY PAYROLL LOOP
# =========================

@tasks.loop(minutes=1)
async def weekly_payroll():
    """
    Κάθε λεπτό τσεκάρει:
    - Αν είναι Παρασκευή
    - Αν είναι συγκεκριμένη ώρα
    και στέλνει μισθούς στο payments.
    """
    now = datetime.datetime.utcnow()
    # 4 = Friday, ώρα 12:00 UTC (14:00 GR/CY περίπου)
    if now.weekday() == 4 and now.hour == 12 and now.minute == 0:
        channel = bot.get_channel(PAYMENTS_CHANNEL_ID)
        if not channel:
            print("❌ Payments channel not found")
            return
        await do_payout(channel, automatic=True)


async def do_payout(channel: discord.TextChannel, automatic: bool = False, invoker: discord.Member | None = None):
    """Λογική πληρωμής: χρησιμοποιείται από το auto loop & την εντολή !payoutnow."""
    if not weekly_totals:
        await channel.send("📢 **Δεν υπάρχουν καταχωρημένες αποδείξεις για αυτή την εβδομάδα.**")
        return

    title = "📢 **Αυτόματη Εβδομαδιαία Πληρωμή**" if automatic else "📢 **Χειροκίνητη Εβδομαδιαία Πληρωμή**"
    if invoker:
        title += f"\n🔧 Εκτελέστηκε από: {invoker.mention}"

    await channel.send(title)

    # Για κάθε χρήστη στον πίνακα
    for user_id, total in weekly_totals.items():
        total_int = int(total)
        member = None
        # Βρες το μέλος σε κάποιο guild
        for guild in bot.guilds:
            m = guild.get_member(int(user_id))
            if m:
                member = m
                break

        # Αν δεν τον βρούμε, απλά στείλε με mention
        if not member:
            mention = f"<@{user_id}>"
            multiplier = 0.0
        else:
            mention = member.mention
            multiplier = get_role_multiplier(member)

        final_pay = int(total_int * multiplier)
        percentage = int(multiplier * 100)

        await channel.send(
            f"👤 {mention}\n"
            f"   📊 Σύνολο εβδομάδας: **{total_int}**\n"
            f"   🏅 Ποσοστό ρόλου: **{percentage}%**\n"
            f"   💸 Τελικός μισθός: **{final_pay}**"
        )

    # Reset μετά την πληρωμή
    weekly_totals.clear()


# =========================
# COMMANDS
# =========================

@bot.command(name="check")
async def check_command(ctx: commands.Context):
    """
    !check
    Δείχνει το τρέχον εβδομαδιαίο σύνολό σου και τον εκτιμώμενο μισθό.
    """
    user_id = str(ctx.author.id)
    total = int(weekly_totals.get(user_id, 0))
    multiplier = get_role_multiplier(ctx.author)
    percentage = int(multiplier * 100)
    final_pay = int(total * multiplier)

    await ctx.send(
        f"{ctx.author.mention}\n"
        f"📊 Τρέχον εβδομαδιαίο σύνολο: **{total}**\n"
        f"🏅 Ποσοστό ρόλου: **{percentage}%**\n"
        f"💸 Εκτιμώμενος μισθός: **{final_pay}**"
    )


@bot.command(name="payoutnow")
@commands.has_permissions(administrator=True)
async def payoutnow_command(ctx: commands.Context):
    """
    !payoutnow
    Κάνει αμέσως payout στο payments κανάλι (Admin only).
    """
    channel = bot.get_channel(PAYMENTS_CHANNEL_ID)
    if not channel:
        await ctx.send("❌ Δεν βρήκα το κανάλι πληρωμών.")
        return

    await do_payout(channel, automatic=False, invoker=ctx.author)
    await ctx.send("✅ Έγινε χειροκίνητη πληρωμή και έγινε reset στα εβδομαδιαία σύνολα.")


@payoutnow_command.error
async def payoutnow_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Χρειάζεσαι δικαίωμα **Administrator** για να τρέξεις αυτή την εντολή.")


@bot.command(name="helpbot")
async def helpbot_command(ctx: commands.Context):
    """
    !helpbot
    Εμφανίζει τις διαθέσιμες εντολές του bot.
    """
    await ctx.send(
        "**Διαθέσιμες εντολές:**\n"
        "`!check` → Δείχνει το εβδομαδιαίο σύνολό σου και τον εκτιμώμενο μισθό.\n"
        "`!payoutnow` → (Admin) Κάνει άμεση πληρωμή στο κανάλι payments.\n"
        "`!helpbot` → Αυτό το μήνυμα.\n\n"
        "Οι αποδείξεις διαβάζονται αυτόματα όταν στέλνονται στο κανάλι proof."
    )


# =========================
# RUN BOT
# =========================

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ ERROR: Το DISCORD_TOKEN δεν βρέθηκε στο περιβάλλον (Render env var).")
    else:
        bot.run(DISCORD_TOKEN)






