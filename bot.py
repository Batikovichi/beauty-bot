import logging
import os
from datetime import datetime, timedelta
from calendar import monthrange
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from database import Database

# ─── SETĂRI ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8695808600:AAHT5Bk6fZ3-Jinvh3OqL5lIy4clG33PBaM")
MASTER_CHAT_ID = int(os.getenv("MASTER_CHAT_ID", "817286796"))       
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@Unghi_chisinau_bot") 

WORK_START    = "09:00"
WORK_END      = "19:00"
SLOT_DURATION = 60

SERVICES = [
    ("Manichiură",              "250 lei"),
    ("Manichiură + ojă gel",    "350 lei"),
    ("Pedichiură",              "300 lei"),
    ("Pedichiură + ojă gel",    "400 lei"),
    ("Unghii false",            "500 lei"),
    ("Corecție",                "350 lei"),
]

PRICE_LIST = "💅 Listă de prețuri\n\n" + "\n".join(
    f"✨ {s} — {p}" for s, p in SERVICES
) + "\n\n⏱ Durată: 1–2 ore\n📍 Adresa: specificați la programare"

# ─── STĂRI ────────────────────────────────────────────────────────────────────
(C_SERVICE, C_DATE, C_TIME, C_PHONE, C_CONFIRM) = range(5)
(M_NAME, M_PHONE, M_SERVICE, M_DATE, M_TIME, M_SOURCE, M_NOTES) = range(10, 17)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
db = Database("bookings.db")

DAY_NAMES  = ["Lu", "Ma", "Mi", "Jo", "Vi", "Sb", "Du"]
MONTH_NAMES = ["","Ianuarie","Februarie","Martie","Aprilie","Mai","Iunie",
               "Iulie","August","Septembrie","Octombrie","Noiembrie","Decembrie"]
SRC_ICON  = {"bot":"🤖","instagram":"📸","phone":"📞","manual":"✍️"}
SRC_LABEL = {"bot":"Bot","instagram":"Instagram","phone":"Telefon","manual":"Manual"}

# ─── HELPERS ──────────────────────────────────────────────────────────────────

def is_master(uid): return uid == MASTER_CHAT_ID

def main_menu(uid):
    if is_master(uid):
        return ReplyKeyboardMarkup([
            ["📅 Programare nouă (manual)", "📋 Toate programările"],
            ["📊 Statistici",               "📅 Programările de azi"],
        ], resize_keyboard=True)
    return ReplyKeyboardMarkup([
        ["📅 Programare",        "💰 Prețuri"],
        ["📸 Portofoliu",        "❌ Anulare programare"],
        ["📋 Programările mele"],
    ], resize_keyboard=True)

async def check_sub(update, context):
    if not CHANNEL_USERNAME: return True
    try:
        m = await context.bot.get_chat_member(CHANNEL_USERNAME, update.effective_user.id)
        return m.status not in ["left","kicked"]
    except: return True

def available_slots(date_str):
    booked = {b["time"] for b in db.get_bookings_for_date(date_str)}
    start  = datetime.strptime(date_str + " " + WORK_START, "%Y-%m-%d %H:%M")
    end    = datetime.strptime(date_str + " " + WORK_END,   "%Y-%m-%d %H:%M")
    slots, cur = [], start
    while cur + timedelta(minutes=SLOT_DURATION) <= end:
        t = cur.strftime("%H:%M")
        if t not in booked: slots.append(t)
        cur += timedelta(minutes=SLOT_DURATION)
    return slots

def build_calendar(year: int, month: int, prefix: str, master_mode=False) -> InlineKeyboardMarkup:
    """Строит inline-календарь на месяц. prefix = 'cd' для клиента, 'md' для мастера."""
    today    = datetime.now().date()
    min_date = today + timedelta(days=1)           # завтра минимум
    max_date = today + timedelta(days=365)         # год вперёд

    rows = []

    # Заголовок с навигацией
    prev_y, prev_m = (year, month-1) if month > 1 else (year-1, 12)
    next_y, next_m = (year, month+1) if month < 12 else (year+1, 1)

    # Кнопка «назад» только если предыдущий месяц >= текущий
    can_prev = datetime(prev_y, prev_m, 1).date() >= datetime(today.year, today.month, 1).date()
    can_next = datetime(next_y, next_m, 1).date() <= datetime(max_date.year, max_date.month, 1).date()

    nav = []
    nav.append(InlineKeyboardButton(
        f"◀️" if can_prev else " ", callback_data=f"{prefix}_nav_{prev_y}_{prev_m}" if can_prev else "noop"
    ))
    nav.append(InlineKeyboardButton(f"{MONTH_NAMES[month]} {year}", callback_data="noop"))
    nav.append(InlineKeyboardButton(
        f"▶️" if can_next else " ", callback_data=f"{prefix}_nav_{next_y}_{next_m}" if can_next else "noop"
    ))
    rows.append(nav)

    # Дни недели
    rows.append([InlineKeyboardButton(d, callback_data="noop") for d in ["Lu","Ma","Mi","Jo","Vi","Sb","Du"]])

    # Дни месяца
    first_weekday, days_in_month = monthrange(year, month)  # 0=Mon
    # понедельник=0 по monthrange, наш Lu=0 тоже — совпадает
    week = [InlineKeyboardButton(" ", callback_data="noop")] * first_weekday
    for day in range(1, days_in_month + 1):
        d = datetime(year, month, day).date()
        if d < min_date or d > max_date or d.weekday() == 6:
            btn = InlineKeyboardButton(" ", callback_data="noop")
        else:
            ds    = d.strftime("%Y-%m-%d")
            slots = available_slots(ds)
            if slots:
                label = str(day)
            else:
                label = "·"  # занято
            btn = InlineKeyboardButton(label, callback_data=f"{prefix}_pick_{ds}" if slots else "noop")
        week.append(btn)
        if len(week) == 7:
            rows.append(week)
            week = []
    if week:
        while len(week) < 7:
            week.append(InlineKeyboardButton(" ", callback_data="noop"))
        rows.append(week)

    return InlineKeyboardMarkup(rows)

def build_time_keyboard(date_str: str, prefix: str) -> InlineKeyboardMarkup:
    slots = available_slots(date_str)
    kb, row = [], []
    for s in slots:
        row.append(InlineKeyboardButton(s, callback_data=f"{prefix}_time_{s}"))
        if len(row) == 4: kb.append(row); row = []
    if row: kb.append(row)
    return InlineKeyboardMarkup(kb)

# ─── START ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name
    text = (f"Bună, {name}! 👋 Ești în modul master." if is_master(uid)
            else f"Bună, {name}! 👋\nAlege secțiunea:")
    await update.message.reply_text(text, reply_markup=main_menu(uid))

# ─── CLIENT INFO ──────────────────────────────────────────────────────────────

async def show_prices(update, context):
    await update.message.reply_text(PRICE_LIST)

PORTFOLIO_FOLDERS = [
    ("manicura",      "💅 Manichiură"),
    ("manicura_gel",  "💅 Manichiură + ojă gel"),
    ("pedicura",      "🦶 Pedichiură"),
    ("pedicura_gel",  "🦶 Pedichiură + ojă gel"),
    ("unghii_false",  "✨ Unghii false"),
    ("corectie",      "🔧 Corecție"),
]

async def show_portfolio(update, context):
    kb = []
    for folder, label in PORTFOLIO_FOLDERS:
        path = os.path.join("portfolio", folder)
        if os.path.exists(path):
            photos = [f for f in os.listdir(path) if f.endswith((".jpg",".jpeg",".png"))]
            if photos:
                kb.append([InlineKeyboardButton(label, callback_data=f"portfolio_{folder}")])
    if not kb:
        await update.message.reply_text("📸 Portofoliul nu este încă disponibil.\nRevino curând! 😊")
        return
    await update.message.reply_text(
        "📸 Alege serviciul pentru a vedea lucrările:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def portfolio_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    folder = q.data.replace("portfolio_", "")
    path   = os.path.join("portfolio", folder)
    label  = next((l for f,l in PORTFOLIO_FOLDERS if f == folder), folder)
    if not os.path.exists(path):
        await q.edit_message_text("📸 Fotografii indisponibile momentan.")
        return
    photos = [f for f in os.listdir(path) if f.endswith((".jpg",".jpeg",".png"))]
    if not photos:
        await q.edit_message_text(f"📸 {label}\n\nNu sunt fotografii încă.")
        return
    await q.edit_message_text(f"📸 {label} — {len(photos)} foto:")
    for p in photos[:6]:
        with open(os.path.join(path, p), "rb") as f:
            await q.message.reply_photo(f)


async def my_bookings(update, context):
    rows = db.get_user_bookings(update.effective_user.id)
    if not rows:
        await update.message.reply_text("Nu ai programări active."); return
    text = "📋 Programările tale:\n\n"
    for b in rows:
        d = datetime.strptime(b["date"],"%Y-%m-%d")
        text += f"• {d.strftime('%d.%m.%Y')} la {b['time']} — {b.get('service','—')}\n"
    await update.message.reply_text(text)

async def cancel_start(update, context):
    rows = db.get_user_bookings(update.effective_user.id)
    if not rows:
        await update.message.reply_text("Nu ai programări active de anulat."); return
    kb = []
    for b in rows:
        d = datetime.strptime(b["date"],"%Y-%m-%d")
        kb.append([InlineKeyboardButton(
            f"{d.strftime('%d.%m')} {b['time']} — {b.get('service','')}",
            callback_data=f"cancel_{b['id']}")])
    await update.message.reply_text("Alege programarea de anulat:", reply_markup=InlineKeyboardMarkup(kb))

async def cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    bid = int(q.data.replace("cancel_",""))
    b   = db.get_booking_by_id(bid)
    if b:
        db.delete_booking(bid)
        d = datetime.strptime(b["date"],"%Y-%m-%d")
        await q.edit_message_text(f"✅ Programarea din {d.strftime('%d.%m.%Y')} la {b['time']} anulată.")
        if MASTER_CHAT_ID:
            u = update.effective_user
            await context.bot.send_message(MASTER_CHAT_ID,
                f"❌ Programare anulată!\n👤 {u.full_name}\n💅 {b.get('service','—')}\n📅 {d.strftime('%d.%m.%Y')} la {b['time']}")
    else:
        await q.edit_message_text("Programarea nu a fost găsită.")

# ─── CLIENT BOOKING ───────────────────────────────────────────────────────────

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_sub(update, context):
        kb = [[InlineKeyboardButton("📢 Abonează-te", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")]]
        await update.message.reply_text(f"❗ Abonează-te la {CHANNEL_USERNAME}.", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END
    kb = [[InlineKeyboardButton(f"{n} — {p}", callback_data=f"srv_{i}")] for i,(n,p) in enumerate(SERVICES)]
    await update.message.reply_text("💅 Alege serviciul:", reply_markup=InlineKeyboardMarkup(kb))
    return C_SERVICE

async def c_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    i = int(q.data.replace("srv_",""))
    context.user_data["service"] = f"{SERVICES[i][0]} ({SERVICES[i][1]})"
    now = datetime.now()
    await q.edit_message_text(
        f"✅ {SERVICES[i][0]}\n\n📅 Alege ziua (· = ocupat, Du = liber):",
        reply_markup=build_calendar(now.year, now.month, "cd")
    )
    return C_DATE

async def c_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = q.data

    if data == "noop": return C_DATE

    if data.startswith("cd_nav_"):
        _, _, y, m = data.split("_"); y,m = int(y),int(m)
        await q.edit_message_reply_markup(reply_markup=build_calendar(y, m, "cd"))
        return C_DATE

    if data.startswith("cd_pick_"):
        ds = data.replace("cd_pick_","")
        context.user_data["date"] = ds
        dt = datetime.strptime(ds,"%Y-%m-%d")
        await q.edit_message_text(
            f"📅 {DAY_NAMES[dt.weekday()]} {dt.strftime('%d.%m.%Y')}\n\n⏰ Alege ora:",
            reply_markup=build_time_keyboard(ds,"cd")
        )
        return C_TIME
    return C_DATE

async def c_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["time"] = q.data.replace("cd_time_","")
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Trimite numărul meu", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await q.message.reply_text("📞 Apasă butonul pentru a trimite numărul:", reply_markup=kb)
    return C_PHONE

async def c_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
        if not phone.startswith("+"): phone = "+"+phone
    else:
        phone = update.message.text.strip()
    context.user_data["phone"] = phone

    ds  = context.user_data["date"]
    ts  = context.user_data["time"]
    svc = context.user_data["service"]
    dt  = datetime.strptime(ds,"%Y-%m-%d")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmă", callback_data="cconf_yes"),
        InlineKeyboardButton("❌ Anulează", callback_data="cconf_no")
    ]])
    await update.message.reply_text(
        f"📋 Confirmare:\n\n💅 {svc}\n📅 {dt.strftime('%d.%m.%Y')}\n⏰ {ts}\n📞 {phone}\n\nTotul e corect?",
        reply_markup=kb
    )
    return C_CONFIRM

async def c_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = update.effective_user.id
    if q.data == "cconf_no":
        await q.edit_message_text("❌ Anulat.")
        await q.message.reply_text("Meniu:", reply_markup=main_menu(uid))
        return ConversationHandler.END

    u   = update.effective_user
    ds  = context.user_data["date"]
    ts  = context.user_data["time"]
    svc = context.user_data["service"]
    ph  = context.user_data.get("phone","")
    dt  = datetime.strptime(ds,"%Y-%m-%d")

    db.add_booking(u.id, u.full_name, ds, ts, phone=ph, service=svc, source="bot")
    await q.edit_message_text(
        f"✅ Ești programat(ă)!\n\n💅 {svc}\n📅 {dt.strftime('%d.%m.%Y')} la {ts}\n\nCu 24h înainte vei primi memento. Ne vedem! 💅"
    )
    await q.message.reply_text("Meniu:", reply_markup=main_menu(uid))

    if MASTER_CHAT_ID:
        uname = f"@{u.username}" if u.username else "fără username"
        await context.bot.send_message(MASTER_CHAT_ID,
            f"🔔 Programare nouă!\n\n👤 {u.full_name} ({uname})\n📞 {ph or '—'}\n💅 {svc}\n📅 {dt.strftime('%d.%m.%Y')} la {ts}\n📌 🤖 Bot"
        )
    return ConversationHandler.END

# ─── MASTER MANUAL ADD ────────────────────────────────────────────────────────

async def m_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_master(update.effective_user.id):
        await update.message.reply_text("❌ Acces interzis.")
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text("✍️ Adăugare manuală\n\n👤 Numele clientului:",
                                    reply_markup=ReplyKeyboardRemove())
    return M_NAME

async def m_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["m_name"] = update.message.text.strip()
    await update.message.reply_text("📞 Numărul de telefon:")
    return M_PHONE

async def m_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["m_phone"] = update.message.text.strip()
    kb = [[InlineKeyboardButton(f"{n} — {p}", callback_data=f"msrv_{i}")] for i,(n,p) in enumerate(SERVICES)]
    await update.message.reply_text("💅 Alege serviciul:", reply_markup=InlineKeyboardMarkup(kb))
    return M_SERVICE

async def m_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    i = int(q.data.replace("msrv_",""))
    context.user_data["m_service"] = f"{SERVICES[i][0]} ({SERVICES[i][1]})"
    now = datetime.now()
    await q.edit_message_text(
        f"✅ {SERVICES[i][0]}\n\n📅 Alege ziua:",
        reply_markup=build_calendar(now.year, now.month, "md", master_mode=True)
    )
    return M_DATE

async def m_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    data = q.data

    if data == "noop": return M_DATE

    if data.startswith("md_nav_"):
        _, _, y, m = data.split("_"); y,m = int(y),int(m)
        await q.edit_message_reply_markup(reply_markup=build_calendar(y, m, "md", master_mode=True))
        return M_DATE

    if data.startswith("md_pick_"):
        ds = data.replace("md_pick_","")
        context.user_data["m_date"] = ds
        dt = datetime.strptime(ds,"%Y-%m-%d")
        await q.edit_message_text(
            f"📅 {DAY_NAMES[dt.weekday()]} {dt.strftime('%d.%m.%Y')}\n\n⏰ Alege ora:",
            reply_markup=build_time_keyboard(ds,"md")
        )
        return M_TIME
    return M_DATE

async def m_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["m_time"] = q.data.replace("md_time_","")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Bot",       callback_data="msrc_bot"),
         InlineKeyboardButton("📸 Instagram", callback_data="msrc_instagram")],
        [InlineKeyboardButton("📞 Telefon",   callback_data="msrc_phone"),
         InlineKeyboardButton("✍️ Manual",    callback_data="msrc_manual")],
    ])
    await q.edit_message_text("📌 De unde vine clientul?", reply_markup=kb)
    return M_SOURCE

async def m_source(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["m_source"] = q.data.replace("msrc_","")
    await q.edit_message_text("📝 Note adiționale (sau trimite «-» dacă nu sunt):")
    return M_NOTES

async def m_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = update.message.text.strip()
    if notes == "-": notes = ""

    m  = context.user_data
    dt = datetime.strptime(m["m_date"],"%Y-%m-%d")

    # Сохраняем сразу — без кнопки подтверждения
    db.add_booking(
        user_id=None,
        user_name=m["m_name"],
        date=m["m_date"],
        time=m["m_time"],
        phone=m["m_phone"],
        service=m["m_service"],
        source=m["m_source"],
        notes=notes
    )

    sl = SRC_LABEL.get(m["m_source"], m["m_source"])
    await update.message.reply_text(
        f"✅ Programare salvată!\n\n"
        f"👤 {m['m_name']}\n"
        f"📞 {m['m_phone']}\n"
        f"💅 {m['m_service']}\n"
        f"📅 {dt.strftime('%d.%m.%Y')} la {m['m_time']}\n"
        f"📌 {sl}\n"
        f"📝 {notes or '—'}",
        reply_markup=main_menu(update.effective_user.id)
    )
    return ConversationHandler.END

# ─── MASTER VIEW ──────────────────────────────────────────────────────────────

async def m_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_master(update.effective_user.id): return
    rows = db.get_all_bookings()
    if not rows:
        await update.message.reply_text("Nu sunt programări viitoare."); return
    by_date = {}
    for b in rows: by_date.setdefault(b["date"],[]).append(b)
    text = "📋 Toate programările:\n\n"
    for ds in sorted(by_date):
        dt = datetime.strptime(ds,"%Y-%m-%d")
        text += f"━━ {DAY_NAMES[dt.weekday()]} {dt.strftime('%d.%m.%Y')} ━━\n"
        for b in sorted(by_date[ds], key=lambda x: x["time"]):
            ico = SRC_ICON.get(b.get("source",""),"📌")
            text += f"  {b['time']} {ico} {b['user_name']}\n  💅 {b.get('service','—')}  📞 {b.get('phone','—')}\n"
        text += "\n"
    if len(text) > 4000: text = text[:4000]+"\n..."
    await update.message.reply_text(text)

async def m_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_master(update.effective_user.id): return
    today = datetime.now().strftime("%Y-%m-%d")
    rows  = db.get_bookings_for_date(today)
    if not rows:
        await update.message.reply_text("📅 Nu sunt programări pentru azi."); return
    dt   = datetime.now()
    text = f"📅 Azi {DAY_NAMES[dt.weekday()]} {dt.strftime('%d.%m.%Y')}:\n\n"
    for b in sorted(rows, key=lambda x: x["time"]):
        ico = SRC_ICON.get(b.get("source",""),"📌")
        text += f"🕐 {b['time']} {ico} {b['user_name']}\n   💅 {b.get('service','—')}\n   📞 {b.get('phone','—')}\n\n"
    await update.message.reply_text(text)

async def m_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_master(update.effective_user.id): return
    s   = db.get_stats()
    src = "\n".join(f"  {SRC_ICON.get(r['source'],'📌')} {SRC_LABEL.get(r['source'],r['source'])}: {r['cnt']}"
                    for r in s["by_source"]) or "  —"
    svc = "\n".join(f"  {r['service']}: {r['cnt']}" for r in s["by_service"][:5]) or "  —"
    await update.message.reply_text(
        f"📊 Statistici:\n\n📌 Total: {s['total']}\n📅 Azi: {s['today']}\n🗓 Luna: {s['this_month']}\n\n"
        f"Pe surse:\n{src}\n\nTop servicii:\n{svc}"
    )

# ─── REMINDERS ────────────────────────────────────────────────────────────────

async def reminders(context: ContextTypes.DEFAULT_TYPE):
    tomorrow = (datetime.now()+timedelta(days=1)).strftime("%Y-%m-%d")
    for b in db.get_bookings_for_date(tomorrow):
        if not b.get("user_id"): continue
        try:
            dt = datetime.strptime(b["date"],"%Y-%m-%d")
            await context.bot.send_message(b["user_id"],
                f"⏰ Memento!\n\nMâine ai programare:\n💅 {b.get('service','')}\n"
                f"📅 {dt.strftime('%d.%m.%Y')} la {b['time']}\n\nTe așteptăm! 💅")
        except Exception as e: logger.warning(f"Reminder: {e}")

# ─── TEXT ROUTER ──────────────────────────────────────────────────────────────

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t   = update.message.text
    uid = update.effective_user.id
    if is_master(uid):
        if   t == "📋 Toate programările":    await m_all(update, context)
        elif t == "📅 Programările de azi":   await m_today(update, context)
        elif t == "📊 Statistici":             await m_stats(update, context)
        else: await update.message.reply_text("Folosește butoanele 👇", reply_markup=main_menu(uid))
    else:
        if   t == "💰 Prețuri":               await show_prices(update, context)
        elif t == "📸 Portofoliu":             await show_portfolio(update, context)
        elif t == "📋 Programările mele":      await my_bookings(update, context)
        elif t == "❌ Anulare programare":     await cancel_start(update, context)
        else: await update.message.reply_text("Folosește butoanele 👇", reply_markup=main_menu(uid))

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    client_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📅 Programare$"), book_start)],
        states={
            C_SERVICE: [CallbackQueryHandler(c_service, pattern="^srv_")],
            C_DATE:    [CallbackQueryHandler(c_date,    pattern="^(cd_nav_|cd_pick_|noop)")],
            C_TIME:    [CallbackQueryHandler(c_time,    pattern="^cd_time_")],
            C_PHONE:   [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), c_phone)],
            C_CONFIRM: [CallbackQueryHandler(c_confirm, pattern="^cconf_")],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    master_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📅 Programare nouă \\(manual\\)$"), m_start)],
        states={
            M_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, m_name)],
            M_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, m_phone_input)],
            M_SERVICE: [CallbackQueryHandler(m_service, pattern="^msrv_")],
            M_DATE:    [CallbackQueryHandler(m_date,    pattern="^(md_nav_|md_pick_|noop)")],
            M_TIME:    [CallbackQueryHandler(m_time,    pattern="^md_time_")],
            M_SOURCE:  [CallbackQueryHandler(m_source,  pattern="^msrc_")],
            M_NOTES:   [MessageHandler(filters.TEXT & ~filters.COMMAND, m_notes)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(client_conv)
    app.add_handler(master_conv)
    app.add_handler(CallbackQueryHandler(cancel_cb,    pattern="^cancel_"))
    app.add_handler(CallbackQueryHandler(portfolio_cb, pattern="^portfolio_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.job_queue.run_daily(reminders, time=datetime.strptime("10:00","%H:%M").time())

    logger.info("Botul a pornit!")
    app.run_polling()

if __name__ == "__main__":
    main()
