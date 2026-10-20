import os, json, re, html, shutil, random, smtplib, time, urllib.request, urllib.parse, datetime
from email.message import EmailMessage
from collections import Counter

CITY = os.getenv("CITY", "Karachi")
CATEGORIES = os.getenv("CATEGORIES", "restaurant,cafe,hairdresser,beauty,bakery,dentist,gym").split(",")
BUILD_PER_RUN = int(os.getenv("BUILD_PER_RUN", "10"))
EMAIL_PER_RUN = int(os.getenv("EMAIL_PER_RUN", "10"))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
SENDER_NAME = os.getenv("SENDER_NAME", "Web Helper")
SENDER_ADDRESS = os.getenv("SENDER_ADDRESS", "Your postal address")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
REPO = os.getenv("GITHUB_REPOSITORY", "user/repo")
OWNER, NAME = REPO.split("/")
BASE_URL = f"https://{OWNER}.github.io/{NAME}"
TODAY = datetime.date.today().isoformat()

def load(p, d):
    try: return json.load(open(p))
    except Exception: return d

leads = load("leads.json", {})
unsub = set(open("unsubscribed.txt").read().lower().split()) if os.path.exists("unsubscribed.txt") else set()

URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]

def run_query(q):
    for attempt in range(3):
        for url in URLS:
            try:
                req = urllib.request.Request(url, urllib.parse.urlencode({"data": q}).encode(), {"User-Agent": "leadbot/1.0 (github actions)"})
                return json.load(urllib.request.urlopen(req, timeout=60))["elements"]
            except Exception as e:
                print("overpass failed", url, e)
        time.sleep(15 * (attempt + 1))
    return None

def geocode(city):
    try:
        u = "https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" + urllib.parse.quote(city)
        r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "leadbot/1.0 (github actions)"}), timeout=30))
        lat, lon = float(r[0]["lat"]), float(r[0]["lon"]); d = 0.08
        print("geocoded", city, lat, lon)
        return f"{lat-d},{lon-d},{lat+d},{lon+d}"
    except Exception as e:
        print("geocode failed", city, e)
        return None

def overpass_one(CITY):
    out = []
    bbox = geocode(CITY)
    if not bbox: return out
    for c in CATEGORIES:
        c = c.strip()
        f = '["name"][!"website"][!"contact:website"]'
        q = f'[out:json][timeout:40];(nwr({bbox})["amenity"="{c}"]{f};nwr({bbox})["shop"="{c}"]{f};nwr({bbox})["leisure"="{c}"]{f};);out center tags 200;'
        els = run_query(q)
        if els is None:
            print("servers busy, giving up for", CITY, "- will retry on the next daily run")
            break
        print("overpass ok", CITY, c, len(els), "results")
        out += els
        time.sleep(3)
    return out

def overpass():
    out = []
    for c in os.getenv("CITY", "Karachi").split(","):
        if c.strip(): out += overpass_one(c.strip())
    return out

CHAIN_KEYS = ("brand", "brand:wikidata", "brand:website", "operator:wikidata", "website", "contact:website")

def is_chain(t, counts=None):
    if any(k in t for k in CHAIN_KEYS): return True
    return bool(counts) and counts.get((t.get("name") or "").lower(), 0) >= 3

def wa_number(p):
    d = re.sub(r"\D", "", (p or "").split(";")[0])
    if d.startswith("00"): d = d[2:]
    if d.startswith("0"): d = "92" + d[1:]
    return d if re.fullmatch(r"923\d{9}", d) else ""

def score(t):
    s = 0
    if "wikidata" in t or "wikipedia" in t: s += 5
    if wa_number(t.get("phone") or t.get("contact:phone")): s += 2
    for k in ("phone", "contact:phone", "opening_hours"): s += 1 if k in t else 0
    if "email" in t or "contact:email" in t: s += 3
    if "contact:facebook" in t or "contact:instagram" in t: s += 2
    return s

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "place"

TEMPLATE_VERSION = 4
# primary, soft, accent, icon, label, display-font-kind, floating emojis
THEMES = {
    "restaurant": ("#9f1d1d", "#fff0e8", "#ffb703", "🍽️", "Restaurant", "serif", ["🍽️", "🍕", "🥘", "✨"]),
    "fast_food": ("#b91c1c", "#fff0e8", "#ffc107", "🍔", "Restaurant", "sans", ["🍔", "🍟", "🥤", "✨"]),
    "cafe": ("#5b3a29", "#f6ece2", "#e9a23b", "☕", "Café", "serif", ["☕", "🥐", "🍰", "✨"]),
    "bakery": ("#8f3a17", "#fff0e0", "#f0b04a", "🥐", "Bakery", "serif", ["🥐", "🍞", "🧁", "✨"]),
    "hairdresser": ("#6d2160", "#fbe8f6", "#f5b94f", "💇", "Salon", "serif", ["💇", "✂️", "💅", "✨"]),
    "beauty": ("#9c1a58", "#ffe6f2", "#f5b94f", "💅", "Beauty salon", "serif", ["💅", "💄", "🌸", "✨"]),
    "dentist": ("#07607a", "#e3f5fa", "#2bd4bd", "🦷", "Dental clinic", "sans", ["🦷", "😁", "✨", "🪥"]),
    "gym": ("#14161d", "#eceef3", "#ff5a36", "💪", "Gym", "sans", ["💪", "🏋️", "🔥", "⚡"]),
    "fitness_centre": ("#14161d", "#eceef3", "#ff5a36", "💪", "Gym", "sans", ["💪", "🏋️", "🔥", "⚡"]),
}
DEFAULT_THEME = ("#1b3558", "#e8eefa", "#f5b94f", "📍", "Local business", "sans", ["📍", "✨", "⭐", "💬"])
FONTS = {"serif": ("'Fraunces',Georgia,'Times New Roman',serif", "Fraunces:wght@600;800"),
         "sans": ("'Sora','Plus Jakarta Sans',system-ui,sans-serif", "Sora:wght@600;800")}

ICONS = {
 "phone": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
 "chat": '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/>',
 "pin": '<path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
 "dl": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>',
 "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/>',
 "check": '<path d="M20 6L9 17l-5-5"/>',
 "fb": '<path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/>',
 "ig": '<rect x="2" y="2" width="20" height="20" rx="5"/><path d="M16 11.4a4 4 0 1 1-3.4-3.4 4 4 0 0 1 3.4 3.4z"/><path d="M17.5 6.5h.01"/>',
 "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
}
def ic(n):
    return '<svg class="i" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[n] + '</svg>'

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-flash-lite-latest"
AI_PER_RUN = int(os.getenv("AI_PER_RUN") or "10")
ai_state = {"calls": 0, "off": False}

def ai_content(t, kind, area, chips):
    if not GEMINI_KEY or ai_state["off"] or ai_state["calls"] >= AI_PER_RUN: return None
    ai_state["calls"] += 1
    facts = {"name": t.get("name"), "type": kind, "cuisine": t.get("cuisine"), "area": area, "city": t.get("addr:city"),
             "features": chips, "opening_hours": t.get("opening_hours")}
    facts = {k: v for k, v in facts.items() if v}
    prompt = ("Write website copy for a small local business using ONLY these facts: " + json.dumps(facts, ensure_ascii=False) +
              ". Do NOT invent anything: no prices, years, awards, reviews, menu items, owners, 'best', 'family-owned' or 'famous'. "
              "Return JSON with keys: tagline (max 8 words, English), about (2-3 friendly sentences, English), "
              "about_ur (the same about text in natural Urdu), tagline_ur (the tagline in natural Urdu).")
    try:
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6}}).encode()
        req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent", body,
                                     {"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY})
        r = json.load(urllib.request.urlopen(req, timeout=60))
        txt = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
        d = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        out = {k: str(d[k]).strip()[:n] for k, n in (("tagline", 90), ("about", 600), ("tagline_ur", 120), ("about_ur", 900)) if d.get(k)}
        time.sleep(7)
        return out if "about" in out and "tagline" in out else None
    except urllib.error.HTTPError as ex:
        print("AI error", ex.code, GEMINI_MODEL, ex.read()[:200])
        if ex.code in (400, 401, 403, 404, 429): ai_state["off"] = True
    except Exception as ex:
        print("AI failed", ex)
    return None

CSS = r"""
@property --ang{syntax:'<angle>';initial-value:0deg;inherits:false}
:root{--p:__P__;--a:__A__;--soft:__S__;--fd:__FD__;--bg:#fbfaf8;--fg:#15171f;--muted:#5d6475;--card:#fff;--line:#e9e7e2;--pt:__P__}
__DARKMEDIA__
*{box-sizing:border-box}html{scroll-behavior:smooth;overflow-x:hidden}
body{margin:0;overflow-x:hidden;font-family:'Plus Jakarta Sans',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--fg);line-height:1.7;-webkit-font-smoothing:antialiased}
.i{width:1.15em;height:1.15em;flex:none}
.ur{display:none;font-family:'Noto Naskh Arabic','Segoe UI',serif;line-height:2.1}body.lang-ur .ur{display:block}body.lang-ur .en{display:none}
.wrap{max-width:1040px;margin:0 auto;padding:0 22px}
#prog{position:fixed;top:0;left:0;height:3px;width:0;background:linear-gradient(90deg,var(--a),var(--p));z-index:60}
.spot{position:fixed;inset:0;pointer-events:none;z-index:1;opacity:0;transition:opacity .4s;background:radial-gradient(520px circle at var(--x,50%) var(--y,50%),color-mix(in srgb,var(--a) 13%,transparent),transparent 65%)}
.draft{background:#fff3cd;color:#5c4400;text-align:center;padding:8px 12px;font-size:.8rem;position:relative;z-index:25}
nav{position:sticky;top:0;z-index:40;backdrop-filter:blur(16px) saturate(1.4);-webkit-backdrop-filter:blur(16px) saturate(1.4);background:color-mix(in srgb,var(--bg) 70%,transparent);border-bottom:1px solid var(--line)}
nav .wrap{display:flex;align-items:center;justify-content:space-between;height:62px;gap:10px}
.brand{font-family:var(--fd);font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:52%;font-size:1.05rem}
.nr{display:flex;gap:8px;align-items:center}
.ib{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:8px 15px;font:inherit;font-size:.85rem;cursor:pointer;transition:.25s;display:inline-flex;gap:8px;align-items:center}.ib:hover{transform:translateY(-2px);border-color:var(--pt);box-shadow:0 6px 16px rgba(0,0,0,.1)}
.hero{position:relative;min-height:min(92vh,840px);display:flex;align-items:center;justify-content:center;overflow:hidden;color:#fff;text-align:center;isolation:isolate;padding:70px 0 120px;background:linear-gradient(160deg,color-mix(in srgb,var(--p) 78%,#000) 0%,var(--p) 55%,color-mix(in srgb,var(--p) 72%,var(--a)) 100%)}
.hero:before{content:"";position:absolute;inset:0;z-index:-1;opacity:.14;mix-blend-mode:overlay;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
.blob{position:absolute;border-radius:50%;filter:blur(80px);z-index:-2;animation:fl 16s ease-in-out infinite alternate;will-change:transform}
.o1{width:520px;height:520px;background:var(--a);top:-180px;left:-120px;opacity:.5}.o2{width:440px;height:440px;background:#ffffff;opacity:.16;bottom:-160px;right:-80px;animation-delay:-6s}.o3{width:300px;height:300px;background:var(--a);opacity:.3;bottom:10%;left:58%;animation-delay:-10s}
@keyframes fl{to{transform:translate(70px,50px) scale(1.2)}}
.pe{position:absolute;bottom:-70px;left:var(--l);font-size:var(--s);opacity:.2;z-index:-1;animation:rise var(--t) linear var(--d) infinite;filter:saturate(.8)}
@keyframes rise{to{transform:translateY(-115vh) rotate(var(--r))}}
.ico{font-size:3.4rem;line-height:1;display:inline-block;animation:bob 4s ease-in-out infinite;filter:drop-shadow(0 10px 18px rgba(0,0,0,.3))}@keyframes bob{50%{transform:translateY(-10px) rotate(-5deg)}}
.badge{display:inline-flex;align-items:center;padding:6px 16px;border-radius:999px;font-size:.8rem;font-weight:700;margin:10px 0 4px;backdrop-filter:blur(8px);border:1px solid #ffffff40}
.badge[hidden]{display:none}.badge.on{background:#16a34acc}.badge.off{background:#ffffff26}
.badge.on:before{content:"";width:8px;height:8px;border-radius:50%;background:#bbf7d0;margin-right:8px;animation:pulse 1.6s infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 #bbf7d0aa}100%{box-shadow:0 0 0 10px #bbf7d000}}
h1{font-family:var(--fd);font-size:clamp(2.4rem,9vw,5.2rem);line-height:1.04;margin:10px 0 6px;font-weight:800;letter-spacing:-.025em;text-wrap:balance}
.w{display:inline-block;animation:wd .9s cubic-bezier(.2,.8,.2,1) both;animation-delay:calc(.2s + var(--i)*.13s)}
@keyframes wd{from{opacity:0;transform:translateY(46px) rotate(4deg);filter:blur(8px)}}
.fu{animation:fu .9s cubic-bezier(.2,.8,.2,1) both;animation-delay:calc(.3s + var(--i,0)*.14s)}@keyframes fu{from{opacity:0;transform:translateY(24px)}}
.ul{width:96px;height:5px;border-radius:9px;background:var(--a);margin:18px auto 0;transform-origin:left;animation:gr 1s .9s cubic-bezier(.2,.8,.2,1) both}@keyframes gr{from{transform:scaleX(0)}}
.tag{font-size:clamp(1.05rem,2.6vw,1.4rem);opacity:.95;margin:22px auto 6px;max-width:660px}
.kind{opacity:.8;letter-spacing:.16em;text-transform:uppercase;font-size:.76rem;font-weight:700}
.btns{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;margin-top:30px}
.btn{display:inline-flex;align-items:center;gap:10px;padding:14px 28px;border-radius:999px;text-decoration:none;font-weight:700;font-size:.96rem;border:0;cursor:pointer;font-family:inherit;transition:transform .2s,box-shadow .3s;will-change:transform}
.btn:hover{box-shadow:0 14px 30px rgba(0,0,0,.3)}.btn:active{transform:scale(.96)!important}
.c1{background:var(--a);color:#111}.c2{background:#25d366;color:#04301a}.c3{background:#ffffff1f;color:#fff;border:1px solid #ffffff55;backdrop-filter:blur(8px)}
.cue{position:absolute;bottom:92px;left:50%;width:26px;height:42px;border:2px solid #ffffff90;border-radius:14px;transform:translateX(-50%)}
.cue:after{content:"";position:absolute;left:50%;top:8px;width:4px;height:8px;background:#fff;border-radius:3px;transform:translateX(-50%);animation:sc 1.7s infinite}@keyframes sc{60%{transform:translate(-50%,14px);opacity:0}}
.wave{position:absolute;bottom:-1px;left:0;width:100%;height:80px;fill:var(--bg)}
.mqw{overflow:hidden;padding:28px 0 8px;position:relative;z-index:2}
.mq{width:112%;margin-left:-6%;transform:rotate(-1.6deg);background:var(--fg);color:var(--bg);padding:16px 0;box-shadow:0 14px 34px rgba(0,0,0,.18)}
.mt{display:flex;gap:34px;width:max-content;animation:mq 32s linear infinite;font-family:var(--fd);font-weight:800;font-size:1.25rem;white-space:nowrap}
.mt .st{color:var(--a)}@keyframes mq{to{transform:translateX(-50%)}}.mq:hover .mt{animation-play-state:paused}
section{padding:64px 0;position:relative;z-index:2}
.eb{font-size:.74rem;font-weight:800;letter-spacing:.2em;text-transform:uppercase;color:var(--pt);margin-bottom:8px}
h2{font-family:var(--fd);font-size:clamp(1.6rem,4.4vw,2.4rem);line-height:1.15;margin:0 0 18px;letter-spacing:-.02em}
.card{background:var(--card);border:1px solid var(--line);border-radius:26px;padding:30px;box-shadow:0 10px 40px rgba(20,24,40,.07);position:relative}
.gb:before{content:"";position:absolute;inset:-2px;border-radius:28px;padding:2px;pointer-events:none;background:conic-gradient(from var(--ang),var(--a),transparent 28%,var(--pt),transparent 68%,var(--a));-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;animation:rot 7s linear infinite}@keyframes rot{to{--ang:360deg}}
.g2{display:grid;grid-template-columns:1.2fr 1fr;gap:22px}.g1{display:grid;gap:22px}@media(max-width:780px){.g2{grid-template-columns:1fr}}
.lead{font-size:1.1rem;color:var(--fg);position:relative;z-index:1}.wm{position:absolute;right:18px;bottom:-14px;font-size:9rem;line-height:1;opacity:.07;pointer-events:none;user-select:none}.card.gb{overflow:hidden}
.pills{display:flex;flex-wrap:wrap;gap:9px;margin-top:20px}
.pill{display:inline-flex;align-items:center;gap:7px;background:var(--soft);color:var(--pt);border-radius:999px;padding:8px 15px;font-size:.86rem;font-weight:700}.pill .i{width:1em;height:1em;stroke-width:3}
.hr{display:flex;justify-content:space-between;padding:10px 14px;border-radius:12px;font-size:.95rem;transition:.2s}
.hr.today{background:var(--soft);color:var(--pt);font-weight:800}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}
.tile{position:relative;display:flex;flex-direction:column;align-items:flex-start;gap:6px;padding:24px;border-radius:24px;background:var(--card);border:1px solid var(--line);text-decoration:none;color:var(--fg);overflow:hidden;transform:perspective(800px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg));transition:transform .18s ease-out,box-shadow .3s;cursor:pointer;font:inherit;text-align:left;box-shadow:0 8px 28px rgba(20,24,40,.06)}
.tile:hover{box-shadow:0 18px 44px rgba(20,24,40,.16)}
.tile:after{content:"";position:absolute;inset:0;background:radial-gradient(240px circle at var(--mx,50%) var(--my,50%),color-mix(in srgb,var(--a) 30%,transparent),transparent 62%);opacity:0;transition:opacity .3s;pointer-events:none}.tile:hover:after{opacity:1}
.tile .ic{width:52px;height:52px;border-radius:17px;display:grid;place-items:center;background:var(--a);color:#111;font-size:1.3rem;margin-bottom:8px;transition:transform .3s}.tile:hover .ic{transform:rotate(-8deg) scale(1.1)}
.tile b{font-size:1.1rem}.tile small{color:var(--muted);font-size:.85rem;word-break:break-word}.tile .go{position:absolute;right:20px;top:22px;opacity:.35;transition:.3s}.tile:hover .go{opacity:1;transform:translateX(4px)}
form{display:grid;gap:14px}.fl{position:relative}
.fl input,.fl textarea{font:inherit;width:100%;padding:24px 16px 9px;border-radius:16px;border:1.5px solid var(--line);background:var(--bg);color:var(--fg);transition:.2s;resize:vertical}
.fl label{position:absolute;left:17px;top:16px;color:var(--muted);font-size:.95rem;pointer-events:none;transition:.2s}
.fl input:focus,.fl textarea:focus{outline:none;border-color:var(--pt);box-shadow:0 0 0 4px color-mix(in srgb,var(--pt) 18%,transparent)}
.fl input:focus+label,.fl textarea:focus+label,.fl input:not(:placeholder-shown)+label,.fl textarea:not(:placeholder-shown)+label{top:7px;font-size:.7rem;color:var(--pt);font-weight:700}
.mapf{position:relative;height:340px;border-radius:20px;overflow:hidden;margin-top:6px;background:linear-gradient(135deg,var(--soft),var(--bg));display:grid;place-items:center;font-size:3rem}
.mapf iframe{position:absolute;inset:0;width:100%;height:100%;border:0}
a.link{color:var(--pt);font-weight:800;text-decoration:none;display:inline-flex;gap:8px;align-items:center;margin-top:14px}a.link:hover{text-decoration:underline}
.fabs{position:fixed;right:16px;bottom:16px;display:flex;flex-direction:column;gap:10px;z-index:50}
.fab{width:56px;height:56px;border-radius:50%;display:grid;place-items:center;font-size:1.35rem;text-decoration:none;box-shadow:0 10px 26px rgba(0,0,0,.3);transition:transform .2s;animation:pop .6s .9s cubic-bezier(.2,1.4,.4,1) both}.fab:hover{transform:scale(1.12)}
.f1{background:var(--a);color:#111}.f2{background:#25d366;color:#04301a}@keyframes pop{from{transform:scale(0)}}
footer{position:relative;z-index:2;text-align:center;color:var(--muted);font-size:.8rem;padding:30px 20px 44px;overflow:hidden}
.big{font-family:var(--fd);font-weight:800;font-size:clamp(2.6rem,12vw,8rem);line-height:1;color:transparent;-webkit-text-stroke:1.5px var(--line);white-space:nowrap;margin-bottom:24px;overflow:hidden;text-overflow:ellipsis}
.js .rv{opacity:0;transform:translateY(34px);transition:opacity .9s cubic-bezier(.2,.8,.2,1),transform .9s cubic-bezier(.2,.8,.2,1);transition-delay:var(--d,0s)}.js .rv.in{opacity:1;transform:none}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}.js .rv{opacity:1!important;transform:none!important}.spot{display:none}}
"""
DARKVARS = "--bg:#0c0e14;--fg:#eef0f6;--muted:#9aa2b5;--card:#151925;--line:#242a39;--soft:#1c2232;--pt:var(--a)"
DARKMEDIA = "@media(prefers-color-scheme:dark){:root:not([data-theme=light]){" + DARKVARS + "}}\n:root[data-theme=dark]{" + DARKVARS + "}"

JS = r"""
(function(){var d=document,b=d.body,root=d.documentElement,$=function(s){return d.querySelector(s)},$$=function(s){return d.querySelectorAll(s)};
try{var th=localStorage.getItem('th');if(th)root.setAttribute('data-theme',th)}catch(e){}
$('#theme').onclick=function(){var c=root.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');var n=c==='dark'?'light':'dark';root.setAttribute('data-theme',n);try{localStorage.setItem('th',n)}catch(e){}};
var lg=$('#lang');if(lg){lg.onclick=function(){var u=b.classList.toggle('lang-ur');lg.textContent=u?'English':'\u0627\u0631\u062f\u0648'}}
var el=$('#open'),m=/^\s*(?:Mo-Su\s+)?(\d\d):(\d\d)-(\d\d):(\d\d)\s*$/.exec(b.dataset.hours||'');
if(m&&el){var s=+m[1]*60+ +m[2],e=+m[3]*60+ +m[4];if(e<=s)e+=1440;var n=new Date(),t=n.getHours()*60+n.getMinutes();var o=(t>=s&&t<e)||(t+1440>=s&&t+1440<e);el.textContent=o?'Open now':'Closed right now';el.className='badge '+(o?'on':'off');el.hidden=false}
var dow=new Date().getDay();$$('.hr[data-dow]').forEach(function(r){if(+r.dataset.dow===dow)r.classList.add('today')});
var f=$('#msg');if(f){f.onsubmit=function(ev){ev.preventDefault();var t='Hello '+b.dataset.name+'! I am '+f.n.value+'. '+f.m.value;window.open('https://wa.me/'+b.dataset.wa+'?text='+encodeURIComponent(t),'_blank')}}
var sh=$('#share');if(sh){sh.onclick=function(){var u=location.href,sm=sh.querySelector('small');if(navigator.share){navigator.share({title:d.title,url:u}).catch(function(){})}else if(navigator.clipboard){navigator.clipboard.writeText(u);if(sm)sm.textContent='Link copied \u2713'}}}
var vc=$('#vcard');if(vc){vc.onclick=function(){var t='BEGIN:VCARD\nVERSION:3.0\nFN:'+b.dataset.name+'\nTEL;TYPE=CELL:'+b.dataset.phone+'\nEND:VCARD';var a=d.createElement('a');a.href=URL.createObjectURL(new Blob([t],{type:'text/vcard'}));a.download='contact.vcf';d.body.appendChild(a);a.click();a.remove()}}
var pg=$('#prog');addEventListener('scroll',function(){var h=root.scrollHeight-innerHeight;pg.style.width=(h>0?scrollY/h*100:0)+'%'},{passive:true});
if('IntersectionObserver' in window){var io=new IntersectionObserver(function(es){es.forEach(function(x){if(x.isIntersecting){x.target.classList.add('in');io.unobserve(x.target)}})},{threshold:.12});$$('.rv').forEach(function(x){io.observe(x)})}else{$$('.rv').forEach(function(x){x.classList.add('in')})}
if(matchMedia('(hover:hover)').matches&&!matchMedia('(prefers-reduced-motion:reduce)').matches){
var sp=$('.spot');addEventListener('mousemove',function(ev){sp.style.opacity=1;sp.style.setProperty('--x',ev.clientX+'px');sp.style.setProperty('--y',ev.clientY+'px')},{passive:true});
$$('.tile').forEach(function(t){t.addEventListener('mousemove',function(ev){var r=t.getBoundingClientRect(),x=ev.clientX-r.left,y=ev.clientY-r.top;t.style.setProperty('--mx',x+'px');t.style.setProperty('--my',y+'px');t.style.setProperty('--ry',((x/r.width-.5)*10)+'deg');t.style.setProperty('--rx',((.5-y/r.height)*10)+'deg')});t.addEventListener('mouseleave',function(){t.style.setProperty('--rx','0deg');t.style.setProperty('--ry','0deg')})});
$$('.mg').forEach(function(t){t.addEventListener('mousemove',function(ev){var r=t.getBoundingClientRect();t.style.transform='translate('+((ev.clientX-r.left-r.width/2)*.18)+'px,'+((ev.clientY-r.top-r.height/2)*.28)+'px)'});t.addEventListener('mouseleave',function(){t.style.transform=''})});
var hero=$('.hero');addEventListener('scroll',function(){var y=scrollY;if(y<900){$$('.blob').forEach(function(x,i){x.style.translate='0 '+(y*(.08+i*.05))+'px'})}},{passive:true})}
})();
"""

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
def hours_rows(h):
    e = html.escape
    m = re.fullmatch(r"\s*(?:Mo-Su\s+)?(\d\d:\d\d)-(\d\d:\d\d)\s*", h or "")
    if m:
        return "".join(f'<div class="hr" data-dow="{(i + 1) % 7}"><span>{dn}</span><span>{m.group(1)} – {m.group(2)}</span></div>' for i, dn in enumerate(DAYS))
    return f'<div class="hr"><span>Hours</span><span>{e(h)}</span></div>' if h else ""

def about_text(t, key, area):
    nm = t["name"]; where = f" in {area}" if area else ""
    cuisine = ", ".join(c.replace("_", " ") for c in (t.get("cuisine") or "").split(";") if c)
    if key in ("restaurant", "fast_food"): s = f"{nm} is a {cuisine + ' ' if cuisine else ''}restaurant{where}."
    elif key == "cafe": s = f"{nm} is a café{where}."
    elif key == "bakery": s = f"{nm} is a bakery{where}."
    elif key in ("hairdresser", "beauty"): s = f"{nm} is a salon{where}."
    elif key == "dentist": s = f"{nm} is a dental clinic{where}."
    elif key in ("gym", "fitness_centre"): s = f"{nm} is a gym{where}."
    else: s = f"{nm} is a local business{where}."
    return s + " Call or message us to find out more, or just drop by."

def build_site(lead):
    t = lead["tags"]; e = html.escape
    key = t.get("amenity") or t.get("shop") or t.get("leisure") or ""
    p, soft, acc, icon, kind, fk, emojis = THEMES.get(key, DEFAULT_THEME)
    fd, fgoogle = FONTS[fk]
    name = e(t["name"])
    hn = t.get("addr:housenumber", ""); hn = "" if len(hn) > 25 else hn
    area = t.get("addr:suburb") or t.get("addr:place") or t.get("addr:city") or ""
    addr = ", ".join(x for x in [hn, t.get("addr:street"), t.get("addr:suburb"), t.get("addr:city")] if x)
    phone = (t.get("phone") or t.get("contact:phone") or "").split(";")[0].strip()
    wa = wa_number(phone)
    fb = t.get("contact:facebook", ""); ig = t.get("contact:instagram", "")
    if ig and not ig.startswith("http"): ig = "https://instagram.com/" + ig.lstrip("@")
    chips = []
    for k, lbl in (("delivery", "Delivery"), ("takeaway", "Takeaway"), ("outdoor_seating", "Outdoor seating"), ("air_conditioning", "Air conditioned"), ("wheelchair", "Wheelchair accessible"), ("drive_through", "Drive-through")):
        if t.get(k) == "yes": chips.append(lbl)
    if t.get("internet_access") in ("wlan", "yes", "wifi"): chips.append("Wi-Fi")
    if "yes" in (t.get("payment:cards"), t.get("payment:credit_cards"), t.get("payment:debit_cards")): chips.append("Cards accepted")
    if t.get("payment:cash") == "yes": chips.append("Cash accepted")
    if t.get("male") == "yes" and t.get("female") == "yes": chips.append("Men & women")
    elif t.get("female") == "yes": chips.append("Ladies")
    elif t.get("male") == "yes": chips.append("Gents")
    for c in (t.get("cuisine") or "").split(";"):
        if c: chips.append(c.replace("_", " ").title())
    ai = lead.get("ai") or {}
    if not ai:
        got = ai_content(t, kind, area, chips)
        if got: lead["ai"] = ai = got
    tag = ai.get("tagline") or f"{kind}" + (f" in {area}" if area else "")
    about = ai.get("about") or about_text(t, key, area)
    ur_about, ur_tag = ai.get("about_ur", ""), ai.get("tagline_ur", "")
    lat, lon = lead["lat"], lead["lon"]; dd = 0.003
    bbox = f"{lon-dd},{lat-dd},{lon+dd},{lat+dd}"
    gdir = f"https://www.google.com/maps/dir/?api=1&amp;destination={lat},{lon}"
    rnd = random.Random(lead["slug"])
    parts = "".join(f'<span class="pe" style="--l:{rnd.randint(2,95)}%;--s:{rnd.randint(22,54)}px;--t:{rnd.randint(16,30)}s;--d:-{rnd.randint(0,30)}s;--r:{rnd.randint(-50,50)}deg">{emojis[i % len(emojis)]}</span>' for i in range(11))
    words = "".join(f'<span class="w" style="--i:{i}">{e(w)}</span> ' for i, w in enumerate(t["name"].split()))
    hrs = t.get("opening_hours", "")
    mq_items = [t["name"], kind] + ([area] if area else []) + ([pretty for pretty in [re.sub(r"^Mo-Su\s+", "Open daily ", hrs)] if hrs]) + chips[:6]
    mq = "".join(f'<span>{e(x)}</span><span class="st">✦</span>' for x in mq_items)
    call = f'<a class="btn c1 mg" href="tel:{e(phone)}">{ic("phone")} Call now</a>' if phone else ""
    wab = f'<a class="btn c2 mg" href="https://wa.me/{wa}">{ic("chat")} WhatsApp</a>' if wa else ""
    fbb = f'<a class="btn c3 mg" href="{e(fb)}">{ic("fb")} Facebook</a>' if fb else ""
    tiles = []
    def tile(tag_, attrs, icon_, title, sub):
        tiles.append(f'<{tag_} class="tile rv" style="--d:{.08*len(tiles):.2f}s" {attrs}><span class="ic">{ic(icon_)}</span><b>{title}</b><small>{sub}</small><span class="go">{ic("arrow")}</span></{tag_}>')
    if phone: tile("a", f'href="tel:{e(phone)}"', "phone", "Call", e(phone))
    if wa: tile("a", f'href="https://wa.me/{wa}"', "chat", "WhatsApp", "Chat instantly")
    tile("a", f'href="{gdir}"', "pin", "Directions", e(area) if area else "Open in Maps")
    if fb: tile("a", f'href="{e(fb)}"', "fb", "Facebook", "Visit our page")
    if ig: tile("a", f'href="{e(ig)}"', "ig", "Instagram", "See our posts")
    if phone: tile("button", 'id="vcard" type="button"', "dl", "Save contact", "Add to your phone")
    tile("button", 'id="share" type="button"', "share", "Share", "Send this page")
    pills = "".join(f'<span class="pill">{ic("check")}{e(c)}</span>' for c in chips)
    rows = hours_rows(hrs)
    contact_card = f'<div class="card rv" style="--d:.12s"><div class="eb">Opening hours</div><h2>When to visit</h2>{rows}</div>' if rows else ""
    form = (f'<div class="card rv"><div class="eb">Say hello</div><h2>Send a message</h2><form id="msg">'
            f'<div class="fl"><input name="n" placeholder=" " required autocomplete="name"><label>Your name</label></div>'
            f'<div class="fl"><textarea name="m" rows="4" placeholder=" " required></textarea><label>How can we help?</label></div>'
            f'<button class="btn c2" type="submit">{ic("chat")} Send on WhatsApp</button></form></div>') if wa else ""
    mapcard = (f'<div class="card rv" style="--d:.1s"><div class="eb">Location</div><h2>Find us</h2><p style="margin:0;color:var(--muted)">{e(addr)}</p>'
               f'<div class="mapf">📍<iframe title="Map" src="https://www.openstreetmap.org/export/embed.html?bbox={bbox}&amp;marker={lat},{lon}" loading="lazy"></iframe></div>'
               f'<a class="link" href="{gdir}">Get directions {ic("arrow")}</a></div>')
    fabs = "".join([f'<a class="fab f1" href="tel:{e(phone)}" aria-label="Call">{ic("phone")}</a>' if phone else "", f'<a class="fab f2" href="https://wa.me/{wa}" aria-label="WhatsApp">{ic("chat")}</a>' if wa else ""])
    ld = {"@context": "https://schema.org", "@type": "LocalBusiness", "name": t["name"], "telephone": phone or None,
          "address": {"@type": "PostalAddress", "streetAddress": addr or None, "addressLocality": t.get("addr:city")},
          "geo": {"@type": "GeoCoordinates", "latitude": lat, "longitude": lon}}
    ldj = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    css = CSS.replace("__P__", p).replace("__S__", soft).replace("__A__", acc).replace("__FD__", fd).replace("__DARKMEDIA__", DARKMEDIA)
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><meta name="theme-color" content="{p}"><meta name="description" content="{e(tag)}"><title>{name}</title>
<script>document.documentElement.className+=' js'</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family={fgoogle}&family=Plus+Jakarta+Sans:wght@400;600;700;800&family=Noto+Naskh+Arabic:wght@400;600&display=swap" rel="stylesheet">
<style>{css}</style><script type="application/ld+json">{ldj}</script></head>
<body data-name="{name}" data-wa="{wa}" data-phone="{e(phone)}" data-hours="{e(hrs)}">
<div id="prog"></div><div class="spot"></div>
<div class="draft">Free draft preview made for {name} by {e(SENDER_NAME)}. Not yet published.</div>
<nav><div class="wrap"><span class="brand" dir="auto">{icon} {name}</span><div class="nr">
{'<button class="ib" id="lang">اردو</button>' if ur_about else ''}<button class="ib" id="theme" aria-label="Toggle dark mode">🌓</button></div></div></nav>
<header class="hero"><div class="blob o1"></div><div class="blob o2"></div><div class="blob o3"></div>{parts}<div class="wrap">
<div class="ico fu">{icon}</div><div class="fu" style="--i:1"><span id="open" class="badge" hidden></span></div>
<h1 dir="auto">{words}</h1><div class="ul"></div>
<p class="tag en fu" style="--i:5">{e(tag)}</p>{f'<p class="tag ur fu" dir="rtl">{e(ur_tag or tag)}</p>' if ur_about else ''}
<div class="kind fu" style="--i:6">{e(kind)}{" · " + e(area) if area else ""}</div>
<div class="btns fu" style="--i:7">{call}{wab}{fbb}</div></div><div class="cue"></div>
<svg class="wave" viewBox="0 0 1440 100" preserveAspectRatio="none"><path d="M0,50 C240,100 480,0 720,40 C960,80 1200,100 1440,45 L1440,100 L0,100 Z"/></svg></header>
<div class="mqw"><div class="mq"><div class="mt">{mq}{mq}{mq}{mq}</div></div></div>
<section><div class="wrap {'g2' if rows else 'g1'}"><div class="card gb rv"><span class="wm">{icon}</span><div class="eb">About us</div><h2 dir="auto">{name}</h2>
<p class="lead en" dir="auto">{e(about)}</p>{f'<p class="lead ur" dir="rtl">{e(ur_about)}</p>' if ur_about else ''}
{f'<div class="pills">{pills}</div>' if pills else ''}</div>{contact_card}</div></section>
<section style="padding-top:8px"><div class="wrap"><div class="eb rv">Get in touch</div><h2 class="rv">Reach us your way</h2><div class="tiles">{"".join(tiles)}</div></div></section>
<section style="padding-top:8px"><div class="wrap {'g2' if form else 'g1'}">{form}{mapcard}</div></section>
<footer><div class="wrap"><div class="big" dir="auto">{name}</div>Draft preview by {e(SENDER_NAME)}. This is not the official website of {name}.<br>Map data &copy; OpenStreetMap contributors</div></footer>
<div class="fabs">{fabs}</div><script>{JS}</script></body></html>'''
    os.makedirs(f"docs/{lead['slug']}", exist_ok=True)
    open(f"docs/{lead['slug']}/index.html", "w", encoding="utf-8").write(page)
    lead["tv"] = TEMPLATE_VERSION

def send(lead):
    to = lead["email"]
    msg = EmailMessage()
    msg["Subject"] = f"A free website draft for {lead['tags']['name']}"
    msg["From"] = f"{SENDER_NAME} <{SMTP_USER}>"; msg["To"] = to
    msg.set_content(f"""Hi,

I noticed {lead['tags']['name']} doesn't have a website listed online, so I built a free draft for you:
{BASE_URL}/{lead['slug']}/

If you like it, reply and I can customize it (photos, menu, your own domain). If not, no problem.
Reply "stop" and I won't contact you again.

{SENDER_NAME}
{SENDER_ADDRESS}
""")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
        s.login(SMTP_USER, SMTP_PASS); s.send_message(msg)

# 0) clean up chain/franchise leads built by older versions
for key, l in leads.items():
    if l.get("tags") and is_chain(l["tags"]) and l.get("status") != "chain_skipped":
        shutil.rmtree(f"docs/{l['slug']}", ignore_errors=True)
        l["status"] = "chain_skipped"

# 0b) rebuild older sites automatically when the template improves
for l in leads.values():
    if l.get("tags") and l.get("status") != "chain_skipped" and l.get("tv") != TEMPLATE_VERSION:
        build_site(l)

# 1) discover + build (local businesses only, no chains)
built = 0
found = overpass()
counts = Counter((e.get("tags", {}).get("name") or "").lower() for e in found)
for el in sorted(found, key=lambda e: -score(e.get("tags", {}))):
    key = f"{el['type']}{el['id']}"
    if key in leads or built >= BUILD_PER_RUN: continue
    if is_chain(el.get("tags", {}), counts): continue
    t = el["tags"]; lat = el.get("lat") or el.get("center", {}).get("lat"); lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None: continue
    lead = {"tags": t, "lat": lat, "lon": lon, "slug": slug(t.get("name:en") or t["name"]) + "-" + str(el["id"])[-4:],
            "email": (t.get("email") or t.get("contact:email") or "").strip().lower(), "built": TODAY,
            "status": "built" if (t.get("email") or t.get("contact:email")) else "no_email"}
    build_site(lead); leads[key] = lead; built += 1
print("built", built)

# 2) email leads built on an earlier day (so the page is already live)
sent = 0
for key, l in leads.items():
    if sent >= EMAIL_PER_RUN: break
    if l["status"] != "built" or l["built"] >= TODAY: continue
    if l["email"] in unsub: l["status"] = "unsubscribed"; continue
    if DRY_RUN or not SMTP_USER:
        print("DRY RUN would email", l["email"], l["slug"]); continue
    try: send(l); l["status"] = "emailed"; l["emailed"] = TODAY; sent += 1; time.sleep(20)
    except Exception as e: print("send failed", l["email"], e)
print("emailed", sent)
def write_outreach():
    wa, fb, calls = [], [], []
    for l in leads.values():
        if l.get("status") not in ("no_email", "built", "emailed") or not l.get("tags"): continue
        t = l["tags"]; nm = t.get("name:en") or t["name"]; url = f"{BASE_URL}/{l['slug']}/"
        ph = (t.get("phone") or t.get("contact:phone") or "").split(";")[0].strip(); n = wa_number(ph)
        msg = f"Hello! I noticed {nm} doesn't have a website, so I made a free draft for you: {url} If you like it I can customize it. Reply STOP and I won't message again."
        if n: wa.append(f"- **{nm}**: [Send on WhatsApp](https://wa.me/{n}?text={urllib.parse.quote(msg)}) | [preview]({url})")
        elif ph: calls.append(f"- **{nm}**: call {ph} | [preview]({url})")
        if t.get("contact:facebook"): fb.append(f"- **{nm}**: [Facebook page]({t['contact:facebook']}) | [preview]({url})")
    open("outreach.md", "w").write("# Outreach list (tap a link, the message is pre-filled)\n\n## WhatsApp (mobile numbers)\n" + ("\n".join(wa) or "_none yet_") +
        "\n\n## Facebook pages (send a message there)\n" + ("\n".join(fb) or "_none yet_") + "\n\n## Phone only (landline)\n" + ("\n".join(calls) or "_none yet_") + "\n")
write_outreach()
json.dump(leads, open("leads.json", "w"), indent=1)
