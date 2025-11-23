import os
import discord
from discord.ext import commands, tasks
import pytesseract
from PIL import Image
import io
import re
import datetime

# ===============================
# CONFIG
# ===============================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

PROOF_CHANNEL_ID = 1433200267947671604
PAYMENTS_CHANNEL_ID = 1433226571501535282

ADMINS = [1420447320650285056]   # <-- Your admin ID

# No tesseract path (Linux Render already has it)
TESSERACT_PATH = None
if TESSERACT_PATH:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# ===============================
# BOT SETUP
# ===============================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# user_id → list of amounts detected
user_payments = {}

amount_regex = re.compile(r"([0-9]{3,5})")

# ===============================
# FUNCTIONS
# ===============================

def is_admin(user_id):
    return user_id in ADMINS

def extract_amounts_from_image(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(image)

        matches = amount_regex.findall(text)

        return [int(x) for x in matches]

    except Exception as e:
        print("OCR ERROR:", e)
        return []

# ===============================
# EVENT: On message with image
# ===============================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Ignore commands here
    if message.content.startswith("!"):
        await bot.process_commands(message)
        return

    # Only read images from proof channel
    if message.channel.id != PROOF_CHANNEL_ID:
        return

    if message.attachments:
        for attachment in message.attachments:
            if attachment.filename.lower().endswith(("png", "jpg", "jpeg")):

                img_bytes = await attachment.read()
                amounts = extract_amounts_from_image(img_bytes)

                if not amounts:
                    await message.channel.send(
                        f"❗ <@{message.author.id}> Δεν βρήκα έγκυρους αριθμούς στην απόδειξη."
                    )
                    return

                total = sum(amounts)

                # Save to the user
                if message.author.id not in user_payments:
                    user_payments[message.author.id] = []

                user_payments[message.author.id].append(total)

                await message.channel.send(
                    f"💰 <@{message.author.id}> Βρέθηκαν **{amounts}** | Σύνολο: **${total}**"
                )

# ===============================
# COMMANDS
# ===============================

@bot.command()
async def total(ctx):
    uid = ctx.author.id
    if uid not in user_payments or len(user_payments[uid]) == 0:
        await ctx.send(f"ℹ️ <@{uid}> δεν έχεις ακόμα καταχωρημένες αποδείξεις.")
        return

    total_sum = sum(user_payments[uid])
    await ctx.send(f"🧾 <@{uid}> το σύνολο σου είναι: **${total_sum}**")


@bot.command()
async def reset(ctx, user: discord.Member = None):
    if not is_admin(ctx.author.id):
        return await ctx.send("⛔ Δεν έχεις δικαίωμα να κάνεις reset.")

    if user is None:
        return await ctx.send("❗ Χρήση: `!reset @user`")

    user_payments[user.id] = []
    await ctx.send(f"♻️ Έγινε reset για: <@{user.id}>")

@bot.command()
async def resetall(ctx):
    if not is_admin(ctx.author.id):
        return await ctx.send("⛔ Δεν έχεις δικαίωμα.")

    user_payments.clear()
    await ctx.send("🧨 Όλα τα δεδομένα διαγράφηκαν.")

# ==========================================
# FIXED HELP COMMAND → NOW !commands
# ==========================================

@bot.command(name="commands")
async def commands_cmd(ctx):
    msg = """
**📘 Commands:**

`!total` → Δείχνει το σύνολο χρημάτων σου  
`!commands` → Λίστα εντολών  

**🔧 Admin Commands:**  
`!reset @user` → Reset για έναν χρήστη  
`!resetall` → Reset όλων  
`!forcepay` → Στέλνει τώρα τη μισθοδοσία
"""
    await ctx.send(msg)

# ===============================
# PAYDAY SYSTEM
# ===============================

@tasks.loop(hours=24)
async def payday():
    now = datetime.datetime.utcnow()
    if now.weekday() == 4:  # Friday
        await send_payments()

async def send_payments():
    channel = bot.get_channel(PAYMENTS_CHANNEL_ID)

    if not user_payments:
        await channel.send("⚠️ Δεν υπάρχουν καταχωρημένες πληρωμές αυτή την εβδομάδα.")
        return

    msg = "📢 **Εβδομαδιαίες Πληρωμές**\n\n"
    for uid, amounts in user_payments.items():
        total = sum(amounts)
        msg += f"👤 <@{uid}> → **${total}**\n"

    await channel.send(msg)

@bot.command()
async def forcepay(ctx):
    if not is_admin(ctx.author.id):
        return await ctx.send("⛔ Δεν έχεις δικαίωμα.")

    await send_payments()
    await ctx.send("📤 Η μισθοδοσία στάλθηκε χειροκίνητα.")

# ===============================
# START
# ===============================

@bot.event
async def on_ready():
    print("Bot is online!")
    payday.start()

bot.run(DISCORD_TOKEN)
