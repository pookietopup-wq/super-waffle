import os, json, sqlite3, secrets, logging, asyncio
from datetime import datetime, timezone
from urllib.parse import urlencode
import httpx
from fastapi import FastAPI, Request, HTTPException
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

# ===================== CONFIG =====================
BOT_TOKEN = "9104234502:AAGPDLTCfz_m5TZXTCSYuPltAtZg8--ajkQ"
OWNER_ID = 8689170506
ADMIN_IDS = []  # Add numeric Telegram admin IDs, e.g. [123456789]
MERCHANT_ID = "6094745816"
PINBOT_API_KEY = "fl_e4008331eb8226bb42bbfb317ac28c7df3f5b22c2144cf57"
BASE_URL = "https://api.pinbot.shop"
PUBLIC_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "./data/hb_topup.sqlite3")
SUPPORT = "@HASAN_BOT_DEV"
CURRENCY = "BDT"
# Set region labels/codes only after confirming Pinbot's accepted region values.
REGIONS = {"bd":"🇧🇩 Bangladesh", "indo":"🇮🇩 Indonesia", "my":"🇲🇾 Malaysia", "sg":"🇸🇬 Singapore"}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hbtopup")
app = FastAPI()
tg = Application.builder().token(BOT_TOKEN).build()
http = httpx.AsyncClient(timeout=45.0, follow_redirects=True)
user_states = {}

def db():
    con=sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory=sqlite3.Row
    return con

def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, balance REAL NOT NULL DEFAULT 0, joined TEXT);
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, region TEXT, category TEXT, title TEXT, item_code TEXT, api_type TEXT, cost REAL DEFAULT 0, price REAL DEFAULT 0, enabled INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, user_id INTEGER, product_id INTEGER, player_id TEXT, region TEXT, title TEXT, sell REAL, supplier REAL DEFAULT 0, charged REAL DEFAULT 0, profit REAL DEFAULT 0, status TEXT, response TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, trxid TEXT UNIQUE, amount REAL, credited REAL, status TEXT, response TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS force_channels(channel TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS payment_methods(name TEXT PRIMARY KEY, number TEXT NOT NULL, instruction TEXT DEFAULT 'Send Money');
        """)
        count=c.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
        if not count:
            seed_products(c)

def seed_products(c):
    rows=[]
    # UC reference items from the supplied documentation
    for code,title in [("20:1","20 UC / 25 Diamonds"),("36:1","36 UC / 50 Diamonds"),("80:1","80 UC / 115 Diamonds"),("160:1","160 UC / 240 Diamonds"),("161:1","Weekly"),("405:1","405 UC / 610 Diamonds"),("800:1","Monthly"),("810:1","810 UC / 1240 Diamonds"),("1625:1","1625 UC / 2530 Diamonds"),("2000:1","2000 UC / Wallet-loadable UC")]:
        rows.append(("bd","uc",title,code,"tp",0,0))
    for code,title in [("50:1","50 SG Shell"),("100:1","100 SG Shell"),("250:1","250 SG Shell"),("320:1","320 SG Shell"),("1000:1","1000 SG Shell")]:
        rows.append(("sg","shell",title,code,"shell",0,0))
    for code,title in [("33:1","33 Indo Shell"),("66:1","66 Indo Shell"),("165:1","165 Indo Shell"),("330:1","330 Indo Shell"),("5:1","5 Indo Diamond"),("50:1","50 Indo Diamond"),("70:1","70 Indo Diamond"),("140:1","140 Indo Diamond"),("355:1","355 Indo Diamond"),("720:1","720 Indo Diamond"),("7290:1","7290 Indo Diamond"),("indoweekly:1","Indo Weekly"),("indomonthly:1","Indo Monthly"),("indobp:1","Indo Booyah Pass"),("indolvl16:1","Indo Level Up 16")]:
        rows.append(("indo","tp",title,code,"tp",0,0))
    for code,title in [("65:1","65 MY Shell"),("130:1","130 MY Shell"),("260:1","260 MY Shell"),("390:1","390 MY Shell"),("650:1","650 MY Shell"),("1300:1","1300 MY Shell"),("2600:1","2600 MY Shell")]:
        rows.append(("my","shell",title,code,"shell",0,0))
    # Direct top-up products explicitly shown in docs
    for code,title in [("lite:1","Weekly Lite"),("evo3:1","3-day Evo Pass"),("evo7:1","7-day Evo Pass"),("evo30:1","30-day Evo Pass"),("lvl6:1","Level Up 6"),("lvl10:1","Level Up 10"),("lvl15:1","Level Up 15"),("lvl20:1","Level Up 20"),("lvl25:1","Level Up 25"),("lvl30:1","Level Up 30"),("lvlall:1","Full Level Up 6–30")]:
        rows.append(("bd","pass",title,code,"tp",0,0))
    for region,cat,title,code,api,cost,price in rows:
        c.execute("INSERT INTO products(region,category,title,item_code,api_type,cost,price) VALUES(?,?,?,?,?,?,?)",(region,cat,title,code,api,cost,price))
    c.execute("INSERT INTO products(region,category,title,item_code,api_type,cost,price) VALUES(?,?,?,?,?,?,?)",("bd","likes","100 Likes","100like","likes",0,0))
    c.execute("INSERT INTO products(region,category,title,item_code,api_type,cost,price) VALUES(?,?,?,?,?,?,?)",("bd","likes","200 Likes","maxlike","likes",0,0))

def is_admin(uid): return uid==OWNER_ID or uid in ADMIN_IDS
def money(x): return f"৳{float(x):.2f}"
def home_kb(admin=False):
    rows=[[InlineKeyboardButton("💎 Top-up Products",callback_data="regions"),InlineKeyboardButton("❤️ Likes",callback_data="likes")],
          [InlineKeyboardButton("💰 Wallet",callback_data="wallet"),InlineKeyboardButton("➕ Deposit",callback_data="deposit")],
          [InlineKeyboardButton("📦 My Orders",callback_data="myorders"),InlineKeyboardButton("🆘 Support",url="https://t.me/"+SUPPORT.lstrip("@"))]]
    if admin: rows.append([InlineKeyboardButton("👑 Admin Panel",callback_data="admin")])
    return InlineKeyboardMarkup(rows)
def admin_kb():
    return InlineKeyboardMarkup([
      [InlineKeyboardButton("📦 Products & Prices",callback_data="ap_products"),InlineKeyboardButton("💳 Deposits",callback_data="ap_deposits")],
      [InlineKeyboardButton("👥 Users",callback_data="ap_users"),InlineKeyboardButton("📊 Statistics",callback_data="ap_stats")],
      [InlineKeyboardButton("📢 Broadcast",callback_data="ap_broadcast"),InlineKeyboardButton("🔒 Force Join",callback_data="ap_force")],
      [InlineKeyboardButton("🏦 Manual Payment Settings",callback_data="ap_payments")],
      [InlineKeyboardButton("🔑 API Status",callback_data="ap_api"),InlineKeyboardButton("⬅️ Home",callback_data="home")]])

async def notify_admins(text):
    for uid in set([OWNER_ID]+ADMIN_IDS):
        try: await tg.bot.send_message(uid,text)
        except Exception: log.exception("Admin notification failed")

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    u=update.effective_user
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(id,name,joined) VALUES(?,?,?)",(u.id,u.full_name,datetime.now(timezone.utc).isoformat()))
        c.execute("UPDATE users SET name=? WHERE id=?",(u.full_name,u.id))
    await update.message.reply_text("🔥 Welcome to HB TOP UP!\n\nChoose a service below.",reply_markup=home_kb(is_admin(u.id)))

async def callback(update:Update, context:ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    uid=q.from_user.id; data=q.data
    if data=="home":
        user_states.pop(uid,None); return await q.edit_message_text("🔥 HB TOP UP\nChoose an option:",reply_markup=home_kb(is_admin(uid)))
    if data=="wallet":
        with db() as c: bal=c.execute("SELECT balance FROM users WHERE id=?",(uid,)).fetchone()
        return await q.edit_message_text(f"💰 Your Wallet: {money(bal['balance'] if bal else 0)}",reply_markup=home_kb(is_admin(uid)))
    if data=="deposit":
        kb=[[InlineKeyboardButton("⚡ Auto Payment (Pinbot)",callback_data="deposit_auto")],
            [InlineKeyboardButton("🏦 Manual Payment",callback_data="deposit_manual")],
            [InlineKeyboardButton("⬅️ Back",callback_data="home")]]
        return await q.edit_message_text("💳 Select your deposit method:",reply_markup=InlineKeyboardMarkup(kb))
    if data=="deposit_auto":
        user_states[uid]={"action":"deposit"}
        return await q.edit_message_text("⚡ Auto Payment\nPayment করার পর Transaction ID পাঠান। Pinbot দিয়ে verify হবে। PIN/Password পাঠাবেন না।")
    if data=="deposit_manual":
        with db() as c: methods=c.execute("SELECT * FROM payment_methods ORDER BY name").fetchall()
        if not methods: return await q.edit_message_text("Manual payment is not configured yet. Contact support.",reply_markup=home_kb(is_admin(uid)))
        kb=[[InlineKeyboardButton(f"{m['name']} — {m['number']}",callback_data=f"manual_method:{m['name']}")] for m in methods]
        return await q.edit_message_text("🏦 Choose a payment method:",reply_markup=InlineKeyboardMarkup(kb))
    if data.startswith("manual_method:"):
        method=data.split(":",1)[1]
        with db() as c: m=c.execute("SELECT * FROM payment_methods WHERE name=?",(method,)).fetchone()
        if not m: return await q.edit_message_text("Payment method unavailable.")
        user_states[uid]={"action":"manual_amount","method":method}
        return await q.edit_message_text(f"🏦 {m['name']}\nNumber: `{m['number']}`\nType: {m['instruction']}\n\nSend the amount you paid (BDT).",parse_mode="Markdown")
    if data.startswith("manual_approve:") or data.startswith("manual_reject:"):
        if not is_admin(uid): return await q.answer("Not authorized",show_alert=True)
        approve=data.startswith("manual_approve:"); depid=int(data.split(":",1)[1])
        with db() as c:
            dep=c.execute("SELECT * FROM deposits WHERE id=?",(depid,)).fetchone()
            if not dep or dep['status']!='pending': return await q.answer("Already processed or not found",show_alert=True)
            info={}
            try: info=json.loads(dep['response'] or '{}')
            except: pass
            if approve:
                c.execute("UPDATE users SET balance=balance+? WHERE id=?",(float(dep['amount']),dep['user_id']))
                c.execute("UPDATE deposits SET credited=amount,status='success' WHERE id=?",(depid,))
            else: c.execute("UPDATE deposits SET status='rejected' WHERE id=?",(depid,))
        try: await tg.bot.send_message(dep['user_id'],("✅ Manual deposit approved. Wallet credited: "+money(dep['amount'])) if approve else "❌ Manual deposit was rejected. Please contact support.")
        except: pass
        await q.edit_message_text(("✅ Approved" if approve else "❌ Rejected")+f"\nDeposit ID: {depid}\nUser: {dep['user_id']}\nAmount: {money(dep['amount'])}")
        return

    if data=="regions":
        kb=[[InlineKeyboardButton(REGIONS[k],callback_data="region:"+k)] for k in REGIONS]
        return await q.edit_message_text("🌍 Select region:",reply_markup=InlineKeyboardMarkup(kb))
    if data.startswith("region:"):
        reg=data.split(":")[1]
        with db() as c: cats=c.execute("SELECT DISTINCT category FROM products WHERE region=? AND enabled=1",(reg,)).fetchall()
        labels={"uc":"💎 UC","shell":"🐚 Shell","tp":"🎮 Top-up / Pass","pass":"🎟 Passes","likes":"❤️ Likes"}
        kb=[[InlineKeyboardButton(labels.get(x["category"],x["category"]),callback_data=f"cat:{reg}:{x['category']}")] for x in cats]
        return await q.edit_message_text(f"{REGIONS[reg]} — select category:",reply_markup=InlineKeyboardMarkup(kb))
    if data.startswith("cat:"):
        _,reg,cat=data.split(":")
        with db() as c: ps=c.execute("SELECT * FROM products WHERE region=? AND category=? AND enabled=1 ORDER BY id",(reg,cat)).fetchall()
        kb=[[InlineKeyboardButton(f"{p['title']} — {money(p['price'])}",callback_data=f"prod:{p['id']}")] for p in ps]
        return await q.edit_message_text("Select product:",reply_markup=InlineKeyboardMarkup(kb))
    if data.startswith("prod:"):
        pid=int(data.split(":")[1])
        with db() as c: p=c.execute("SELECT * FROM products WHERE id=? AND enabled=1",(pid,)).fetchone()
        if not p: return await q.edit_message_text("Product unavailable.")
        if p["price"]<=0: return await q.edit_message_text("এই Product-এর Selling Price Admin এখনো সেট করেনি।")
        user_states[uid]={"action":"order","product_id":pid}
        ask="Send your Free Fire Player ID:" if p["api_type"] in ("tp","likes") else "Confirm purchase? Send YES to continue or /cancel."
        return await q.edit_message_text(f"📦 {p['title']}\n💰 Price: {money(p['price'])}\n{ask}")
    if data=="myorders":
        with db() as c: rows=c.execute("SELECT id,title,status,charged FROM orders WHERE user_id=? ORDER BY created DESC LIMIT 10",(uid,)).fetchall()
        if not rows: return await q.edit_message_text("No orders yet.",reply_markup=home_kb(is_admin(uid)))
        msg="📦 Your recent orders:\n"+"\n".join(f"#{r['id']} — {r['title']} — {r['status']} — {money(r['charged'])}" for r in rows)
        return await q.edit_message_text(msg,reply_markup=home_kb(is_admin(uid)))
    if data=="admin":
        if not is_admin(uid): return await q.answer("Not authorized",show_alert=True)
        return await q.edit_message_text("👑 Admin Panel",reply_markup=admin_kb())
    if data=="ap_products":
        if not is_admin(uid): return
        with db() as c: ps=c.execute("SELECT id,region,title,price,enabled FROM products ORDER BY region,id").fetchall()
        msg="📦 Products (send: PRICE product_id amount OR ON/OFF product_id)\n"+"\n".join(f"{p['id']}. {p['region'].upper()} {p['title']} — {money(p['price'])} — {'ON' if p['enabled'] else 'OFF'}" for p in ps)
        user_states[uid]={"action":"admin_products"}
        return await q.edit_message_text(msg[:4000])
    if data=="ap_deposits":
        if not is_admin(uid): return
        with db() as c: rows=c.execute("SELECT * FROM deposits ORDER BY id DESC LIMIT 10").fetchall()
        msg="💳 Recent deposits:\n"+"\n".join(f"{r['id']} | {r['user_id']} | {r['trxid']} | {money(r['credited'])} | {r['status']}" for r in rows) or "No deposits."
        return await q.edit_message_text(msg[:4000],reply_markup=admin_kb())
    if data=="ap_users":
        if not is_admin(uid): return
        with db() as c: n=c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        return await q.edit_message_text(f"👥 Total users: {n}\nBalance command: ADD user_id amount OR SUB user_id amount",reply_markup=admin_kb())
    if data=="ap_stats":
        if not is_admin(uid): return
        with db() as c:
            n=c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
            sales=c.execute("SELECT COALESCE(SUM(charged),0) x FROM orders").fetchone()["x"]
            profit=c.execute("SELECT COALESCE(SUM(profit),0) x FROM orders").fetchone()["x"]
        return await q.edit_message_text(f"📊 Orders: {n}\nSales: {money(sales)}\nProfit: {money(profit)}",reply_markup=admin_kb())
    if data=="ap_broadcast":
        if not is_admin(uid): return
        user_states[uid]={"action":"broadcast"}
        return await q.edit_message_text("Send the broadcast message.")
    if data=="ap_force":
        if not is_admin(uid): return
        with db() as c: chans=c.execute("SELECT channel FROM force_channels").fetchall()
        user_states[uid]={"action":"force"}
        return await q.edit_message_text("Force Join channels:\n"+"\n".join(x["channel"] for x in chans)+"\n\nSend ADD @channel or DEL @channel")
    if data=="ap_payments":
        if not is_admin(uid): return
        with db() as c: methods=c.execute("SELECT * FROM payment_methods ORDER BY name").fetchall()
        listing="\n".join(f"{m['name']}: {m['number']} ({m['instruction']})" for m in methods) or "No manual methods configured."
        user_states[uid]={"action":"admin_payments"}
        return await q.edit_message_text("🏦 Manual Payment Methods\n"+listing+"\n\nCommands:\nSET bKash|018XXXXXXXX|Send Money\nDEL bKash\n\nSend a command below.",reply_markup=admin_kb())
    if data=="ap_api":
        if not is_admin(uid): return
        return await q.edit_message_text(f"Merchant: {MERCHANT_ID}\nAPI Key configured: {'Yes' if PINBOT_API_KEY.startswith('fl_') and 'PASTE_' not in PINBOT_API_KEY else 'No'}",reply_markup=admin_kb())

async def process_deposit(uid,trxid):
    if not trxid or len(trxid)>100: return "Invalid Transaction ID."
    with db() as c:
        if c.execute("SELECT 1 FROM deposits WHERE trxid=?",(trxid,)).fetchone(): return "❌ This Transaction ID has already been submitted."
        c.execute("INSERT INTO deposits(user_id,trxid,amount,credited,status,created) VALUES(?,?,0,0,'checking',?)",(uid,trxid,datetime.now(timezone.utc).isoformat()))
    try:
        r=await http.post(f"{BASE_URL}/verify?merchant={MERCHANT_ID}",headers={"X-API-Key":PINBOT_API_KEY},json={"trxid":trxid})
        data=r.json()
    except Exception as e:
        data={"success":False,"error":str(e)}
    if data.get("success") is True:
        credited=float(data.get("credited",0))
        with db() as c:
            c.execute("UPDATE deposits SET amount=?,credited=?,status='success',response=? WHERE trxid=?",(float(data.get("raw_amount",0)),credited,json.dumps(data),trxid))
            c.execute("UPDATE users SET balance=balance+? WHERE id=?",(credited,uid))
        await notify_admins(f"💳 DEPOSIT SUCCESS\nUser: {uid}\nTRX: {trxid}\nCredited: {money(credited)}")
        return f"✅ Payment verified!\nCredited: {money(credited)}"
    with db() as c: c.execute("UPDATE deposits SET status='failed',response=? WHERE trxid=?",(json.dumps(data),trxid))
    return "❌ Verification failed: "+str(data.get("error",data.get("message","Please check the Transaction ID.")))

async def place_order(uid,pid,playerid):
    with db() as c:
        p=c.execute("SELECT * FROM products WHERE id=? AND enabled=1",(pid,)).fetchone()
        u=c.execute("SELECT balance FROM users WHERE id=?",(uid,)).fetchone()
        if not p or p["price"]<=0: return "Product unavailable or price not set."
        price=float(p["price"])
        if not u or float(u["balance"])<price: return f"Insufficient balance. Need {money(price)}."
        oid="HB"+secrets.token_hex(5).upper()
        c.execute("UPDATE users SET balance=balance-? WHERE id=?",(price,uid))
        c.execute("INSERT INTO orders(id,user_id,product_id,player_id,region,title,sell,charged,status,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (oid,uid,pid,playerid,p["region"],p["title"],price,price,"processing",datetime.now(timezone.utc).isoformat()))
    headers={"X-API-Key":PINBOT_API_KEY,"Content-Type":"application/json","Authorization":PINBOT_API_KEY}
    try:
        if p["api_type"]=="likes":
            r=await http.post(f"{BASE_URL}/topup",headers=headers,json={"playerid":playerid,"package":p["item_code"],"orderid":oid})
        else:
            endpoint="/shell" if p["api_type"]=="shell" else "/tp"
            body={"item":p["item_code"],"currency":"bdt","credit":"balance","orderid":oid}
            if endpoint=="/tp": body["playerid"]=playerid
            if PUBLIC_URL and endpoint=="/tp": body["url"]=PUBLIC_URL+"/pinbot/callback"
            r=await http.post(f"{BASE_URL}{endpoint}?merchant={MERCHANT_ID}",headers=headers,json=body)
        data=r.json()
    except Exception as e:
        data={"status":"unknown","error":str(e)}
    status=str(data.get("status","")).lower()
    if status=="processing":
        with db() as c: c.execute("UPDATE orders SET status='processing',response=? WHERE id=?",(json.dumps(data),oid))
        await notify_admins(f"🆕 NEW ORDER PROCESSING\nOrder: {oid}\nUser: {uid}\nProduct: {p['title']}\nSelling Price: {money(price)}\nSupplier result pending.")
        return f"⏳ Order {oid} is processing. Result will be sent when Pinbot completes it."
    if status in ("success","partial"):
        supplier=float(data.get("total",0) or 0)
        if status=="partial":
            summary=(data.get("voucher_detail") or data.get("shell_detail") or {}).get("summary",{})
            total=max(1,float(summary.get("total",1))); ok=float(summary.get("success",0))
            charged=round(price*ok/total,2)
        else: charged=price
        refund=max(0,round(price-charged,2))
        profit=round(charged-supplier,2)
        with db() as c:
            c.execute("UPDATE users SET balance=balance+? WHERE id=?",(refund,uid))
            c.execute("UPDATE orders SET status=?,supplier=?,charged=?,profit=?,response=? WHERE id=?",(status,supplier,charged,profit,json.dumps(data),oid))
        msg=f"✅ ORDER {status.upper()}\nOrder: {oid}\nProduct: {p['title']}\nPlayer: {playerid or 'N/A'}\nCharged: {money(charged)}\nRefund: {money(refund)}"
        await tg.bot.send_message(uid,msg)
        await notify_admins(f"🔔 NEW ORDER — {status.upper()}\nOrder: {oid}\nUser: {uid}\nProduct: {p['title']}\nSupplier Cost: {money(supplier)}\nSelling Price Charged: {money(charged)}\n📈 Profit: {money(profit)}")
        return msg
    # Fail / unrecognized response: refund full, mark failed; ambiguous network responses are marked review to avoid double fulfilment.
    if "error" in data and status=="unknown":
        with db() as c: c.execute("UPDATE orders SET status='review',response=? WHERE id=?",(json.dumps(data),oid))
        await notify_admins(f"⚠️ ORDER NEEDS REVIEW\nOrder: {oid}\nUser: {uid}\nAPI/network result unclear. Check Pinbot before refund/retry.")
        return f"⚠️ Order {oid} needs admin review. Balance is reserved, not charged again."
    with db() as c:
        c.execute("UPDATE users SET balance=balance+? WHERE id=?",(price,uid))
        c.execute("UPDATE orders SET status='failed',charged=0,profit=0,response=? WHERE id=?",(json.dumps(data),oid))
    await notify_admins(f"❌ ORDER FAILED\nOrder: {oid}\nUser: {uid}\nProduct: {p['title']}\nRefund: {money(price)}\nProfit: ৳0")
    return f"❌ Order failed. {money(price)} refunded to your wallet."

async def text_handler(update:Update, context:ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id; msg=update.message.text.strip()
    st=user_states.get(uid)
    if not st: return
    action=st.get("action")
    if msg=="/cancel":
        user_states.pop(uid,None); return await update.message.reply_text("Cancelled.",reply_markup=home_kb(is_admin(uid)))
    if action=="deposit":
        user_states.pop(uid,None)
        return await update.message.reply_text(await process_deposit(uid,msg),reply_markup=home_kb(is_admin(uid)))
    if action=="manual_amount":
        try:
            amount=float(msg)
            if amount<=0 or amount>1000000: raise ValueError()
        except ValueError:
            return await update.message.reply_text("Enter a valid amount in BDT.")
        user_states[uid]={"action":"manual_trxid","method":st['method'],"amount":amount}
        return await update.message.reply_text("Now send the payment Transaction ID. Do not send PIN or password.")
    if action=="manual_trxid":
        if len(msg)>100 or len(msg)<3: return await update.message.reply_text("Invalid Transaction ID. Send it again.")
        method=st['method']; amount=float(st['amount'])
        with db() as c:
            duplicate=c.execute("SELECT 1 FROM deposits WHERE trxid=?",(msg,)).fetchone()
            if duplicate: return await update.message.reply_text("This Transaction ID was already submitted.")
            c.execute("INSERT INTO deposits(user_id,trxid,amount,credited,status,response,created) VALUES(?,?,?,0,'pending',?,?)",(uid,msg,amount,json.dumps({"method":method,"transaction_id":msg}),datetime.now(timezone.utc).isoformat()))
            depid=c.execute("SELECT last_insert_rowid()").fetchone()[0]
        user_states.pop(uid,None)
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve",callback_data=f"manual_approve:{depid}"),InlineKeyboardButton("❌ Reject",callback_data=f"manual_reject:{depid}")]])
        await notify_admins(f"🏦 MANUAL DEPOSIT REQUEST\nDeposit: {depid}\nUser: {uid}\nMethod: {method}\nAmount: {money(amount)}\nTRX ID: {msg}")
        for admin in set([OWNER_ID]+ADMIN_IDS):
            try: await tg.bot.send_message(admin,f"Review deposit #{depid}",reply_markup=kb)
            except: pass
        return await update.message.reply_text("✅ Request submitted. Admin will verify your payment and approve it.",reply_markup=home_kb(is_admin(uid)))
    if action=="order":
        pid=st["product_id"]; user_states.pop(uid,None)
        with db() as c: p=c.execute("SELECT api_type FROM products WHERE id=?",(pid,)).fetchone()
        player=msg if p and p["api_type"] in ("tp","likes") else ""
        return await update.message.reply_text(await place_order(uid,pid,player),reply_markup=home_kb(is_admin(uid)))
    if not is_admin(uid): user_states.pop(uid,None); return
    if action=="admin_payments":
        parts=msg.split("|",2)
        try:
            with db() as c:
                if len(parts)==3 and parts[0].strip().upper()=="SET":
                    name,number,instruction=[x.strip() for x in parts]
                    if not name or not number: raise ValueError()
                    c.execute("INSERT INTO payment_methods(name,number,instruction) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET number=excluded.number,instruction=excluded.instruction",(name,number,instruction or "Send Money"))
                    await update.message.reply_text("✅ Manual payment method saved.")
                elif len(parts)==2 and parts[0].strip().upper()=="DEL":
                    c.execute("DELETE FROM payment_methods WHERE name=?",(parts[1].strip(),))
                    await update.message.reply_text("✅ Payment method deleted.")
                else: await update.message.reply_text("Use:\nSET bKash|018XXXXXXXX|Send Money\nDEL bKash")
        except Exception: await update.message.reply_text("Invalid format. Use SET name|number|instruction or DEL name.")
    elif action=="admin_products":
        parts=msg.split()
        try:
            with db() as c:
                if len(parts)==3 and parts[0].upper()=="PRICE":
                    c.execute("UPDATE products SET price=? WHERE id=?",(float(parts[2]),int(parts[1])))
                    await update.message.reply_text("✅ Price updated.")
                elif len(parts)==2 and parts[0].upper() in ("ON","OFF"):
                    c.execute("UPDATE products SET enabled=? WHERE id=?",(1 if parts[0].upper()=="ON" else 0,int(parts[1])))
                    await update.message.reply_text("✅ Product updated.")
                else: await update.message.reply_text("Format: PRICE product_id amount OR ON/OFF product_id")
        except Exception: await update.message.reply_text("Invalid command.")
    elif action=="admin_users":
        parts=msg.split()
        try:
            if len(parts)==3 and parts[0].upper() in ("ADD","SUB"):
                target=int(parts[1]); amount=float(parts[2])
                if amount<=0: raise ValueError()
                with db() as c:
                    exists=c.execute("SELECT 1 FROM users WHERE id=?",(target,)).fetchone()
                    if not exists: raise ValueError()
                    delta=amount if parts[0].upper()=="ADD" else -amount
                    c.execute("UPDATE users SET balance=balance+? WHERE id=?",(delta,target))
                await update.message.reply_text(f"✅ Balance updated for {target}: {money(amount)}")
                try: await tg.bot.send_message(target,f"💰 Admin adjusted your wallet by {money(delta)}.")
                except: pass
            else: await update.message.reply_text("Format: ADD user_id amount OR SUB user_id amount")
        except Exception: await update.message.reply_text("Invalid user ID, amount, or user not found.")
    elif action=="broadcast":
        user_states.pop(uid,None)
        with db() as c: ids=[r["id"] for r in c.execute("SELECT id FROM users").fetchall()]
        sent=0
        for x in ids:
            try: await tg.bot.send_message(x,msg); sent+=1
            except: pass
        await update.message.reply_text(f"Broadcast sent to {sent} users.")
    elif action=="force":
        parts=msg.split(maxsplit=1)
        if len(parts)==2 and parts[0].upper() in ("ADD","DEL"):
            with db() as c:
                if parts[0].upper()=="ADD": c.execute("INSERT OR IGNORE INTO force_channels(channel) VALUES(?)",(parts[1],))
                else: c.execute("DELETE FROM force_channels WHERE channel=?",(parts[1],))
            await update.message.reply_text("✅ Force Join list updated.")
        else: await update.message.reply_text("Use ADD @channel or DEL @channel")

async def force_join_ok(uid, context):
    with db() as c: channels=[r["channel"] for r in c.execute("SELECT channel FROM force_channels").fetchall()]
    for ch in channels:
        try:
            m=await context.bot.get_chat_member(ch,uid)
            if m.status not in ("member","administrator","creator"): return False
        except: return False
    return True

async def gate(update,context):
    uid=update.effective_user.id
    if is_admin(uid): return True
    if not await force_join_ok(uid,context):
        await update.effective_message.reply_text("🔒 আগে আমাদের নির্ধারিত Channel-এ Join করুন, তারপর /start দিন।")
        return False
    return True

async def gated_start(update,context):
    if await gate(update,context): await start(update,context)
async def gated_callback(update,context):
    if await gate(update,context): await callback(update,context)
async def gated_text(update,context):
    if await gate(update,context): await text_handler(update,context)

tg.add_handler(CommandHandler("start",gated_start))
tg.add_handler(CommandHandler("cancel",lambda u,c: text_handler(u,c)))
tg.add_handler(CallbackQueryHandler(gated_callback))
tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,gated_text))

@app.on_event("startup")
async def startup():
    init_db()
    if "PASTE_NEW" in BOT_TOKEN or "PASTE_NEW" in PINBOT_API_KEY: log.warning("Set BOT_TOKEN in bot.py before deployment")
    await tg.initialize()
    await tg.start()
    if PUBLIC_URL:
        await tg.bot.set_webhook(PUBLIC_URL+"/telegram",secret_token=os.getenv("TELEGRAM_WEBHOOK_SECRET",""))
    else:
        log.warning("RENDER_EXTERNAL_URL missing; webhook not configured")

@app.on_event("shutdown")
async def shutdown():
    await tg.stop(); await tg.shutdown(); await http.aclose()

@app.get("/")
async def health(): return {"ok":True,"service":"HB TOP UP"}
@app.post("/telegram")
async def telegram_webhook(request:Request):
    secret=os.getenv("TELEGRAM_WEBHOOK_SECRET","")
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token")!=secret: raise HTTPException(403)
    data=await request.json()
    await tg.update_queue.put(Update.de_json(data,tg.bot))
    return {"ok":True}
@app.post("/pinbot/callback")
async def pinbot_callback(request:Request):
    data=await request.json()
    oid=str(data.get("orderid",""))
    if not oid: return {"ok":False,"error":"missing orderid"}
    with db() as c:
        row=c.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
        if not row: return {"ok":False,"error":"unknown order"}
        if row["status"] not in ("processing","review"): return {"ok":True,"duplicate":True}
        price=float(row["sell"]); status=str(data.get("status","failed")).lower()
        supplier=float(data.get("total",0) or 0)
        if status=="success": charged=price
        elif status=="partial":
            summary=(data.get("voucher_detail") or data.get("shell_detail") or {}).get("summary",{})
            charged=round(price*float(summary.get("success",0))/max(1,float(summary.get("total",1))),2)
        else: charged=0
        refund=max(0,price-charged); profit=round(charged-supplier,2)
        c.execute("UPDATE users SET balance=balance+? WHERE id=?",(refund,row["user_id"]))
        c.execute("UPDATE orders SET status=?,supplier=?,charged=?,profit=?,response=? WHERE id=?",(status,supplier,charged,profit,json.dumps(data),oid))
    await tg.bot.send_message(row["user_id"],f"📦 Order {oid}: {status.upper()}\nCharged: {money(charged)}\nRefund: {money(refund)}")
    await notify_admins(f"🔔 ORDER {status.upper()}\nOrder: {oid}\nUser: {row['user_id']}\nProduct: {row['title']}\nSupplier Cost: {money(supplier)}\nSelling Price Charged: {money(charged)}\n📈 Profit: {money(profit)}")
    return {"ok":True}

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=PORT)
