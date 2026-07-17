# VulnShop — the Klefki practice target

A tiny, **deliberately vulnerable** Flask app that reproduces classes 1–10 of the
[field manual](../index.html) so you can practice driving Claude Code (or your own
hands) through real exploitation on a target you own.

> ⚠️ **Local, authorized practice only.** Every bug in `vulnshop.py` is intentional.
> It binds to `127.0.0.1` on purpose — do **not** deploy it, expose it to a network,
> or run it on a shared host. Running exploits against systems you don't own is a crime.

## Run it

```bash
pip install flask          # the only dependency
python3 vulnshop.py        # serves http://127.0.0.1:5000/
```

Open <http://127.0.0.1:5000/> for the index of vulnerable endpoints.

## The bugs, and a payload that proves each

| # | Class | Endpoint | Try |
|---|-------|----------|-----|
| 1 | SQL injection | `GET /search?q=` | `q=x' UNION SELECT username,password FROM users-- -` dumps creds |
| 1 | SQLi auth bypass | `POST /login` | `username=admin' -- ` logs you in, sets a JWT cookie |
| 2 | Reflected XSS | `GET /search?q=` | `q=<script>alert(1)</script>` executes |
| 2 | Stored XSS | `POST /reviews` | post `<script>steal()</script>`, it renders for every visitor |
| 3 | IDOR | `GET /api/orders/<id>` | `1003` returns the admin's order with no auth |
| 4 | JWT forge | `GET /admin` | forge `{"alg":"none"}` with `role=admin`, or crack the secret `s3cr3t` |
| 5 | SSRF | `GET /avatar?url=` | `url=http://127.0.0.1:5000/internal/creds` leaks "cloud" creds |
| 6 | SSTI → RCE | `GET /greet?name=` | `name={{7*7}}` → 49; then a Jinja2 `os.popen` gadget |
| 6 | Command injection | `GET /ping?host=` | `host=127.0.0.1;id` runs `id` |
| 7 | Path traversal | `GET /download?file=` | `file=../flag.txt` reads outside the files dir |
| 8 | Deserialization | `GET /prefs` | a crafted pickle `prefs` cookie runs code |
| 9 | Mass assignment | `POST /profile` | send `role=admin` to escalate your own account |
| 10 | Exposed secrets | `GET /.env` | secrets served directly; errors are verbose (`debug=True`) |

The report's **worked example** chains several of these into a full compromise.
Point Claude Code at `http://127.0.0.1:5000` (proxied through Burp/mitmproxy) and work
the manual top to bottom.
