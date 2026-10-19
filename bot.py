import os, json, re, html, smtplib, time, urllib.request, urllib.parse, datetime
from email.message import EmailMessage

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

def overpass():
    cats = "|".join(c.strip() for c in CATEGORIES)
    shop = "bakery|hairdresser|beauty"
    q = f'''[out:json][timeout:90];
area["name"="{CITY}"]["boundary"="administrative"]->.a;
(nwr(area.a)["amenity"~"^({cats})$"]["name"][!"website"][!"contact:website"];
 nwr(area.a)["shop"~"^({cats})$"]["name"][!"website"][!"contact:website"];
 nwr(area.a)["leisure"~"^({cats})$"]["name"][!"website"][!"contact:website"];);
out center tags 400;'''
    for url in ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]:
        try:
            req = urllib.request.Request(url, urllib.parse.urlencode({"data": q}).encode(), {"User-Agent": "leadbot/1.0"})
            return json.load(urllib.request.urlopen(req, timeout=120))["elements"]
        except Exception as e:
            print("overpass failed", url, e)
    return []

def score(t):
    s = 0
    if "wikidata" in t or "wikipedia" in t: s += 5
    if "brand" in t: s += 2
    for k in ("phone", "contact:phone", "opening_hours"): s += 1 if k in t else 0
    if "email" in t or "contact:email" in t: s += 3
    if "contact:facebook" in t or "contact:instagram" in t: s += 1
    return s

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "place"

def build_site(lead):
    t = lead["tags"]; e = html.escape
    name = e(t["name"]); cat = e((t.get("cuisine") or t.get("amenity") or t.get("shop") or t.get("leisure") or "").replace("_", " ").title())
    addr = e(", ".join(filter(None, [t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:suburb"), t.get("addr:city", CITY)])))
    phone = e(t.get("phone") or t.get("contact:phone") or ""); hours = e(t.get("opening_hours", ""))
    lat, lon = lead["lat"], lead["lon"]; d = 0.003
    bbox = f"{lon-d},{lat-d},{lon+d},{lat+d}"
    call = f'<a class="btn" href="tel:{phone}">Call {phone}</a>' if phone else ""
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{name}</title>
<style>body{{margin:0;font-family:system-ui,sans-serif;color:#222}}header{{background:#1f3a5f;color:#fff;padding:64px 20px;text-align:center}}
h1{{margin:0 0 8px;font-size:2.2rem}}main{{max-width:720px;margin:auto;padding:24px 20px}}.btn{{display:inline-block;background:#f2a900;color:#000;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600;margin-top:16px}}
iframe{{width:100%;height:320px;border:0;border-radius:8px}}.draft{{background:#fff3cd;text-align:center;padding:8px;font-size:.85rem}}</style></head><body>
<div class="draft">Free draft preview made for {name}. Not yet published.</div>
<header><h1>{name}</h1><div>{cat}</div>{call}</header><main>
<h2>Visit us</h2><p>{addr}</p>{f"<h2>Opening hours</h2><p>{hours}</p>" if hours else ""}
<iframe src="https://www.openstreetmap.org/export/embed.html?bbox={bbox}&marker={lat},{lon}" loading="lazy"></iframe>
<p style="font-size:.8rem;color:#777">Map data &copy; OpenStreetMap contributors</p></main></body></html>'''
    os.makedirs(f"docs/{lead['slug']}", exist_ok=True)
    open(f"docs/{lead['slug']}/index.html", "w").write(page)

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

# 1) discover + build
built = 0
for el in sorted(overpass(), key=lambda e: -score(e.get("tags", {}))):
    key = f"{el['type']}{el['id']}"
    if key in leads or built >= BUILD_PER_RUN: continue
    t = el["tags"]; lat = el.get("lat") or el.get("center", {}).get("lat"); lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None: continue
    lead = {"tags": t, "lat": lat, "lon": lon, "slug": slug(t["name"]) + "-" + str(el["id"])[-4:],
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
json.dump(leads, open("leads.json", "w"), indent=1)
