#!/usr/bin/env python3
"""
VulnShop -- a DELIBERATELY VULNERABLE training web app for the Klefki field manual.

    ###############################################################
    #  FOR LOCAL, AUTHORIZED SECURITY PRACTICE ONLY.              #
    #  Every "bug" in this file is intentional. Do NOT deploy it, #
    #  expose it to a network, or run it on a shared host. It     #
    #  binds to 127.0.0.1 on purpose. See README.md.              #
    ###############################################################

One tiny Flask app that reproduces classes 1-10 of the field manual so you can
practice driving Claude Code (or your own hands) through real exploitation.
Only dependency is Flask:  pip install flask
Run:  python3 vulnshop.py     then browse http://127.0.0.1:5000/
"""
import base64, hashlib, hmac, json, os, pickle, sqlite3, subprocess, urllib.request
from flask import Flask, request, render_template_string, Response, make_response

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET = "s3cr3t"          # (4) intentionally weak, guessable JWT secret
app = Flask(__name__)

# in-process SQLite, single connection (toy; fine for the dev server) ----------
con = sqlite3.connect(":memory:", check_same_thread=False)
con.row_factory = sqlite3.Row
con.executescript("""
CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT);
CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, price REAL);
CREATE TABLE orders(id INTEGER PRIMARY KEY, user_id INTEGER, item TEXT, total REAL);
INSERT INTO users VALUES (1,'admin','S3cur3P@ss!','admin'),
                         (2,'alice','alice123','user'),
                         (3,'bob','hunter2','user');
INSERT INTO products VALUES (1,'Red Apples',3.50),(2,'Bananas',2.00),(3,'Cherries',7.25);
INSERT INTO orders VALUES (1001,2,'Red Apples x3',10.50),
                          (1002,3,'Bananas x2',4.00),
                          (1003,1,'Admin gift card',500.00);
""")
con.commit()
REVIEWS = []               # (2) stored-XSS sink

# --- tiny JWT (HS256), also honors alg:none on the way in (4) -----------------
def b64u(b):  return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def b64ud(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
def make_jwt(payload):
    h = b64u(b'{"alg":"HS256","typ":"JWT"}')
    p = b64u(json.dumps(payload).encode())
    sig = b64u(hmac.new(SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"
def read_jwt(tok):
    try:
        h, p, s = tok.split(".")
        head, payload = json.loads(b64ud(h)), json.loads(b64ud(p))
        if head.get("alg") == "none":                     # VULN: trusts alg:none
            return payload
        want = b64u(hmac.new(SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
        return payload if hmac.compare_digest(want, s) else None
    except Exception:
        return None

PAGE = """<!doctype html><meta charset=utf-8><title>VulnShop</title>
<style>body{font:15px system-ui;margin:2rem;max-width:760px}code{background:#eee;padding:1px 5px}
a{color:#357BB3}h1{color:#b4453a}.warn{background:#fbeeec;border-left:3px solid #b4453a;padding:8px 12px}</style>
<h1>VulnShop &mdash; intentionally vulnerable</h1>
<p class=warn>Training target only. Do not deploy. Try these against the field manual:</p>
<ul>
<li>(1/2) <a href="/search?q=apple">/search?q=</a> &mdash; SQLi + reflected XSS</li>
<li>(2) <a href="/reviews">/reviews</a> &mdash; stored XSS</li>
<li>(1/4) <code>POST /login</code> &mdash; SQLi auth bypass, issues a JWT</li>
<li>(3) <a href="/api/orders/1001">/api/orders/&lt;id&gt;</a> &mdash; IDOR</li>
<li>(4) <a href="/admin">/admin</a> &mdash; JWT role check</li>
<li>(5) <a href="/avatar?url=http://127.0.0.1:5000/">/avatar?url=</a> &mdash; SSRF (try /internal/creds)</li>
<li>(6) <a href="/greet?name=guest">/greet?name=</a> SSTI &middot; <a href="/ping?host=127.0.0.1">/ping?host=</a> cmd injection</li>
<li>(7) <a href="/download?file=welcome.txt">/download?file=</a> &mdash; path traversal</li>
<li>(8) <a href="/prefs">/prefs</a> &mdash; pickle deserialization</li>
<li>(9) <code>POST /profile</code> &mdash; mass assignment, no CSRF token</li>
<li>(10) <a href="/.env">/.env</a> &mdash; exposed secrets &middot; errors are verbose (debug)</li>
</ul>"""

@app.route("/")
def index():
    return PAGE

# (1) SQLi + (2) reflected XSS -------------------------------------------------
@app.route("/search")
def search():
    q = request.args.get("q", "")
    sql = "SELECT name, price FROM products WHERE name LIKE '%%%s%%'" % q   # VULN: SQLi
    try:
        rows = con.execute(sql).fetchall()
        items = "".join(f"<li>{r['name']} &mdash; ${r['price']}</li>" for r in rows)
    except Exception as e:
        items = f"<li>SQL error: {e}</li>"                                  # verbose
    return f"<h2>Results for: {q}</h2><ul>{items}</ul>"                     # VULN: XSS (q raw)

# (2) stored XSS ---------------------------------------------------------------
@app.route("/reviews", methods=["GET", "POST"])
def reviews():
    if request.method == "POST":
        REVIEWS.append(request.form.get("comment", ""))
    body = "".join(f"<div class=r>{c}</div>" for c in REVIEWS)              # VULN: raw render
    return f"""<h2>Reviews</h2>{body}
    <form method=post><input name=comment><button>Post</button></form>"""

# (1) SQLi auth bypass + (4) JWT issuance --------------------------------------
@app.route("/login", methods=["POST"])
def login():
    u = request.form.get("username", "")
    p = request.form.get("password", "")
    sql = "SELECT * FROM users WHERE username='%s' AND password='%s'" % (u, p)   # VULN: SQLi
    row = con.execute(sql).fetchone()
    if not row:
        return "bad creds", 401
    tok = make_jwt({"user": row["username"], "role": row["role"]})
    resp = make_response(f"welcome {row['username']} ({row['role']})")
    resp.set_cookie("token", tok)
    return resp

# (3) IDOR ---------------------------------------------------------------------
@app.route("/api/orders/<int:oid>")
def order(oid):
    row = con.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()      # VULN: no owner check
    if not row:
        return "not found", 404
    return dict(row)

# (4) JWT trust ----------------------------------------------------------------
@app.route("/admin")
def admin():
    claims = read_jwt(request.cookies.get("token", ""))
    if not claims or claims.get("role") != "admin":
        return "403 &mdash; admins only (forge a JWT: weak secret 's3cr3t', or alg:none)", 403
    return "<h2>Admin panel</h2>flag{jwt_forged_or_cracked}"

# (5) SSRF + a would-be-internal secrets endpoint ------------------------------
@app.route("/avatar")
def avatar():
    url = request.args.get("url", "")
    try:
        with urllib.request.urlopen(url, timeout=3) as r:                        # VULN: fetches any URL
            return Response(r.read(), content_type="text/plain")
    except Exception as e:
        return f"fetch error: {e}", 502

@app.route("/internal/creds")
def creds():
    if request.remote_addr != "127.0.0.1":                                       # "internal only"
        return "forbidden", 403
    return {"AccessKeyId": "AKIAFAKE", "SecretAccessKey": "fakeSECRETkey", "note": "reachable via SSRF"}

# (6) SSTI + command injection -------------------------------------------------
@app.route("/greet")
def greet():
    name = request.args.get("name", "guest")
    return render_template_string("<h2>Hi " + name + "</h2>")                     # VULN: SSTI

@app.route("/ping")
def ping():
    host = request.args.get("host", "127.0.0.1")
    out = subprocess.getoutput("ping -c 1 " + host)                              # VULN: cmd injection
    return "<pre>" + out + "</pre>"

# (7) path traversal -----------------------------------------------------------
@app.route("/download")
def download():
    fn = request.args.get("file", "welcome.txt")
    path = os.path.join(APP_DIR, "files", fn)                                    # VULN: no canonicalize
    try:
        with open(path, "rb") as f:
            return Response(f.read(), content_type="text/plain")
    except Exception as e:
        return f"error: {e}", 404

# (8) insecure deserialization -------------------------------------------------
@app.route("/prefs")
def prefs():
    c = request.cookies.get("prefs")
    if not c:
        demo = base64.b64encode(pickle.dumps({"theme": "light"})).decode()
        resp = make_response("prefs set. Now craft a malicious 'prefs' cookie.")
        resp.set_cookie("prefs", demo)
        return resp
    data = pickle.loads(base64.b64decode(c))                                     # VULN: pickle of user input
    return f"prefs loaded: {data}"

# (9) mass assignment, no CSRF token -------------------------------------------
@app.route("/profile", methods=["POST"])
def profile():
    claims = read_jwt(request.cookies.get("token", ""))
    if not claims:
        return "login first", 401
    fields = dict(request.form)                                                  # VULN: trusts every field
    if "role" in fields:                                                         # incl. role -> priv-esc
        con.execute("UPDATE users SET role=? WHERE username=?", (fields["role"], claims["user"]))
        con.commit()
    return f"updated {claims['user']}: {fields}"

# (10) exposed secrets ---------------------------------------------------------
@app.route("/.env")
def dotenv():
    return Response("JWT_SECRET=s3cr3t\nDB_PASSWORD=prod-db-pw\nAWS_KEY=AKIAFAKE\n",
                    content_type="text/plain")                                   # VULN: shipped secrets

if __name__ == "__main__":
    os.makedirs(os.path.join(APP_DIR, "files"), exist_ok=True)
    wf = os.path.join(APP_DIR, "files", "welcome.txt")
    if not os.path.exists(wf):
        open(wf, "w").write("Welcome to VulnShop. Try ?file=../flag.txt\n")
    flag = os.path.join(APP_DIR, "flag.txt")
    if not os.path.exists(flag):
        open(flag, "w").write("flag{path_traversal_ok}\n")
    print(" VulnShop on http://127.0.0.1:5000  (training target -- do not expose)")
    app.run(host="127.0.0.1", port=5000, debug=True)   # debug=True -> verbose errors on purpose
