import os
import json
import discord
from discord.ext import commands

# =========================
#  CONFIG
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Channel για πληρωμές
PAYMENTS_CHANNEL_ID = 1433226571501535282

# Admin users (IDs)
ADMINS = [1420447320650285056]

# Ποσοστά ανά ρόλο
ROLE_PERCENTAGES = {
    "Original Boss": 0.30,
    "Vice Boss": 0.25,
    "Manager": 0.20,
    "Worker": 0.15,
    "Delivery": 0.10,
}

DATA_FILE = "data.json"  # εδώ σώζουμε τα σύνολα


# =========================
#  ΒΟΗΘΗΤΙΚΑ
# =========================

def load_totals() -> dict:
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_totals(totals: dict):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(totals, f)
    except Exception as e:
        print("Error saving data.json:", e)


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


def get_role_percent(member: discord.Member) -> float:
    """
    Επιστρέφει το ποσοστό για τον ρόλο του χρήστη.
    Αν έχει παραπάνω από έναν από τους ρόλους, παίρνει το μεγαλύτερο ποσοστό.
    Αν δεν έχει κανέναν από τους ρόλους μας → 0.
    """
    if not member:
        return 0.0

    best = 0.0
    for role in member.roles:
        if role.name in ROLE_PERCENTAGES:
            value = ROLE_PERCENTAGES[role.name]
            if value > best:
                best = value
    return best


# =========================
#  BOT SETUP
# =========================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# user_id(str) -> total bills (int)
totals = load_totals()


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print(f"Loaded totals: {totals}")


# =========================
#  COMMANDS
# =========================

@bot.command(name="bill")
async def bill_cmd(ctx: commands.Context, amount: int):
    """
    !bill <amount>
    Προσθέτει ένα λογαριασμό στον χρήστη.
    """
    if amount <= 0:
        return await ctx.send("❌ Δώσε ένα ποσό μεγαλύτερο από 0.")

    uid = str(ctx.author.id)
    totals[uid] = totals.get(uid, 0) + amount
    save_totals(totals)

    await ctx.send(
        f"🧾 {ctx.author.mention} προστέθηκε bill **${amount}**.\n"
        f"📊 Νέο σύνολο bills: **${totals[uid]}**"
    )


@bot.command(name="total")
async def total_cmd(ctx: commands.Context):
    """
    !total
    Δείχνει το τρέχον σύνολο bills του χρήστη.
    """
    uid = str(ctx.author.id)
    total = totals.get(uid, 0)
    if total == 0:
        return await ctx.send(f"ℹ️ {ctx.author.mention} δεν έχεις ακόμα bills.")

    await ctx.send(f"📊 {ctx.author.mention} το σύνολο bills σου είναι **${total}**.")


@bot.command(name="pay")
async def pay_cmd(ctx: commands.Context, member: discord.Member):
    """
    !pay @user
    Υπολογίζει πληρωμή για έναν χρήστη και τη στέλνει στο κανάλι πληρωμών.
    ΜΟΝΟ ADMIN.
    """
    if not is_admin(ctx.author.id):
        return await ctx.send("⛔ Δεν έχεις δικαίωμα να κάνεις pay.")

    uid = str(member.id)
    total = totals.get(uid, 0)
    if total == 0:
        return await ctx.send(f"ℹ️ {member.mention} δεν έχει bills για πληρωμή.")

    percent = get_role_percent(member)
    if percent <= 0:
        await ctx.send(
            f"⚠️ {member.mention} δεν έχει κάποιον από τους ρόλους πληρωμής, "
            f"άρα ποσοστό 0%. (βάλε έναν ρόλο όπως Worker, Delivery κτλ)"
        )

    final_pay = int(total * percent)

    payments_channel = bot.get_channel(PAYMENTS_CHANNEL_ID)
    if payments_channel is None:
        return await ctx.send("❌ Δεν βρήκα το κανάλι πληρωμών.")

    percent_str = int(percent * 100)

    await payments_channel.send(
        f"💸 **Payment για {member.mention}**\n"
        f"🧾 Bills: **${total}**\n"
        f"🏅 Ρόλος ποσοστού: **{percent_str}%**\n"
        f"💰 Τελικό ποσό πληρωμής: **${final_pay}**"
    )

    await ctx.send(f"✅ Η πληρωμή για {member.mention} στάλθηκε στο κανάλι πληρωμών.")

    # ΜΕΤΑ ΤΗΝ ΠΛΗΡΩΜΗ → μηδενίζει το σύνολο
    totals[uid] = 0
    save_totals(totals)


@bot.command(name="payall")
async def payall_cmd(ctx: commands.Context):
    """
    !payall
    Πληρώνει όλους όσους έχουν bills.
    ΜΟΝΟ ADMIN.
    """
    if not is_admin(ctx.author.id):
        return await ctx.send("⛔ Δεν έχεις δικαίωμα να κάνεις payall.")

    payments_channel = bot.get_channel(PAYMENTS_CHANNEL_ID)
    if payments_channel is None:
        return await ctx.send("❌ Δεν βρήκα το κανάλι πληρωμών.")

    if not totals:
        return await ctx.send("ℹ️ Δεν υπάρχουν bills για πληρωμή.")

    await payments_channel.send("📢 **Μαζική πληρωμή (payall)**")

    for guild in bot.guilds:
        for member in guild.members:
            uid = str(member.id)
            if uid not in totals or totals[uid] == 0:
                continue

            total = totals[uid]
            percent = get_role_percent(member)
            percent_str = int(percent * 100)
            final_pay = int(total * percent)

            await payments_channel.send(
                f"👤 {member.mention}\n"
                f"   🧾 Bills: **${total}**\n"
                f"   🏅 Ποσοστό: **{percent_str}%**\n"
                f"   💰 Πληρωμή: **${final_pay}**"
            )

            totals[uid] = 0

    save_totals(totals)
    await ctx.send("✅ Ολοκληρώθηκε το payall και έγινε reset στα totals.")


@bot.command(name="reset")
async def reset_cmd(ctx: commands.Context, member: discord.Member):
    """
    !reset @user
    Μηδενίζει τα bills ενός χρήστη.
    ΜΟΝΟ ADMIN.
    """
    if not is_admin(ctx.author.id):
        return await ctx.send("⛔ Δεν έχεις δικαίωμα να κάνεις reset.")

    uid = str(member.id)
    totals[uid] = 0
    save_totals(totals)
    await ctx.send(f"♻️ Έγινε reset για {member.mention}.")


@bot.command(name="resetall")
async def resetall_cmd(ctx: commands.Context):
    """
    !resetall
    Μηδενίζει ΟΛΟΥΣ.
    ΜΟΝΟ ADMIN.
    """
    if not is_admin(ctx.author.id):
        return await ctx.send("⛔ Δεν έχεις δικαίωμα να κάνεις resetall.")

    totals.clear()
    save_totals(totals)
    await ctx.send("🧨 Όλα τα totals μηδενίστηκαν.")


@bot.command(name="commands")
async def commands_cmd(ctx: commands.Context):
    """
    !commands
    Δείχνει όλες τις εντολές.
    """
    text = """
**📘 Commands:**

`!bill <amount>` → προσθέτει bill στο σύνολό σου  
`!total` → δείχνει το σύνολο bills σου  

**🔧 Admin Commands:**

`!pay @user` → πληρωμή ενός χρήστη, στέλνεται στο κανάλι πληρωμών  
`!payall` → πληρωμή για όλους όσους έχουν bills  
`!reset @user` → μηδενίζει ένα χρήστη  
`!resetall` → μηδενίζει όλους
"""
    await ctx.send(text)


# =========================
#  START BOT
# =========================

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN env var δεν βρέθηκε.")
    else:
        bot.run(DISCORD_TOKEN)
