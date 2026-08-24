#!/usr/bin/env python3
"""Build a self-contained static archive of cache.bwang.io.

Reads the mirrored source pages from SRC, rewrites them to use local assets and
local .html links, injects an "no longer maintained" notice, and regenerates a
complete index listing every post. Idempotent: re-running rebuilds from SRC.

Layout of the built site:

    index.html  reading.html  standalone.html  private.html   feed index pages
    cache/<slug>/index.html                                   blog posts
    reading/<slug>/index.html                                 reading articles
    private/<slug>/index.html                                 encrypted posts
    404.html                                                  forwards old URLs
    assets/                                                   css, fonts, img
    _mirror/                                                  page sources
    _private/                                                 private sources

Everything outside _mirror/, _private/ and assets/ is generated; don't hand-edit
it. The one exception is the natively-authored reading articles, which have no
mirror source and are only re-trayed in place (see retray_native_reading).
"""
import os
import re
import sys
import json
import html
import hmac
import base64
import getpass
import hashlib
import secrets
import datetime
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
import aesgcm
import markdown

# Paths are resolved relative to this script so the build is portable and
# self-contained: the mirrored Write.as / GitHub-Pages sources live in _mirror/
# inside the repo (committed, not in ephemeral /tmp), and output goes to the repo
# root. Override with CACHE_SRC / CACHE_OUT env vars if needed.
ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("CACHE_SRC", os.path.join(ROOT, "_mirror"))
OUT = os.environ.get("CACHE_OUT", ROOT)
# Plaintext sources for the private feed. Git-ignored: nothing in here should
# ever be committed, only the encrypted output built from it.
PRIVATE_SRC = os.environ.get("CACHE_PRIVATE_SRC", os.path.join(ROOT, "_private"))

# Canonical address of the archived blog (used for og:url + sitemap.xml). Change
# this if the archive is deployed somewhere else.
BASE_URL = "https://cache.bwang.io"

# Blog posts used to sit at the repo root as bare <slug>.html, which put a dozen
# files next to the build script and the site config. They now live one per
# directory under cache/, matching how reading/ and private/ are laid out, so
# the root is just the four feed pages plus site metadata. The old URLs are kept
# alive from inside 404.html (see build_redirects); set this False once the
# links have aged out and the forwarding can go.
POST_DIR = "cache"
REDIRECT_OLD_POST_URLS = True
POSTS_DIR_NOTE = f"{POST_DIR}/"


def post_url(slug):
	"""Site-root-relative URL of a blog post."""
	return f"{POST_DIR}/{slug}/index.html"

# One shared favicon on every page (a layered/"cache" stack mark in the accent
# blue), replacing the leftover Write.as icon on cache posts and the per-article
# icons on the reading pages.
_FAVICON_SVG = (
	"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32' fill='none' "
	"stroke='#357BB3' stroke-width='2.5' stroke-linejoin='round'>"
	"<path d='M16 4 28 10 16 16 4 10Z'/><path d='M4 16 16 22 28 16'/>"
	"<path d='M4 22 16 28 28 22'/></svg>"
)
FAVICON_HREF = "data:image/svg+xml," + urllib.parse.quote(_FAVICON_SVG)
FAVICON_TAG = f'<link rel="icon" href="{FAVICON_HREF}">'

# A small "back to top" control injected on every article page (cache + reading):
# appears after scrolling, smooth-scrolls up. Helps long reads on phones, where
# the right-hand outline is hidden. Self-contained (own style + tiny script).
BACKTOTOP = """<a href="#top" class="to-top" aria-label="Back to top" title="Back to top">↑</a>
<style>
.to-top{position:fixed;bottom:22px;right:22px;z-index:2147483646;width:40px;height:40px;
	display:flex;align-items:center;justify-content:center;border-radius:50%;
	background:rgba(255,255,255,.85);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
	border:1px solid rgba(140,140,140,.28);color:#555;font-size:19px;line-height:1;text-decoration:none;
	opacity:0;pointer-events:none;transition:opacity .25s ease;box-shadow:0 2px 8px rgba(0,0,0,.1);}
.to-top.show{opacity:1;pointer-events:auto;}
.to-top:hover{color:#111;border-color:rgba(140,140,140,.5);}
@media (prefers-reduced-motion:reduce){.to-top{transition:none;}html{scroll-behavior:auto;}}
</style>
<script>(function(){var b=document.querySelector('.to-top');if(!b)return;
function f(){b.classList.toggle('show',window.scrollY>500);}
window.addEventListener('scroll',f,{passive:true});f();
b.addEventListener('click',function(e){e.preventDefault();window.scrollTo({top:0,behavior:'smooth'});});})();</script>"""


# Google Analytics (gtag.js), injected site-wide right after <head> on every
# built page. Guarded so a page that already carries the tag isn't doubled.
GA_ID = "G-4E4BE1S6R6"
GA_TAG = f"""<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{GA_ID}');
</script>"""


def inject_ga(text):
	"""Add the Google Analytics tag right after the opening <head> tag."""
	if "googletagmanager.com/gtag" in text:
		return text
	return re.sub(r'(<head\b[^>]*>)', r'\1\n' + GA_TAG.replace("\\", r"\\"),
	              text, count=1, flags=re.I)


def set_favicon(text):
	"""Replace any existing favicon link(s) with the shared one; insert before
	</head> if the page has none."""
	new, n = re.subn(
		r'<link[^>]*\brel=(["\'])(?:shortcut )?icon\1[^>]*>',
		FAVICON_TAG, text, flags=re.I,
	)
	if n == 0:
		new = re.sub(r'</head>', FAVICON_TAG + "\n</head>", new, count=1, flags=re.I)
	return new


def inject_backtotop(text):
	"""Add the back-to-top control just before </body>."""
	return re.sub(r'</body>', BACKTOTOP + "\n</body>", text, count=1, flags=re.I)


def external_anchor(url, label, cls):
	"""Anchor for a live external app: new tab, screen-reader + hover hints, and a
	decorative ↗ that's hidden from assistive tech."""
	esc = html.escape(label)
	return (
		f'<a class="{cls}" href="{url}" target="_blank" rel="noopener" '
		f'title="{esc} — live external app, opens in a new tab" '
		f'aria-label="{esc}, opens in a new tab">'
		f'{esc} <span aria-hidden="true">↗</span></a>'
	)


def add_og_tags(text, title, rel_path):
	"""Ensure consistent Open Graph / Twitter-card tags in <head>, reusing the
	page's existing <meta name=description> when present. No-op if og:title is
	already there."""
	if 'property="og:title"' in text:
		return text
	dm = re.search(r'<meta name="description" content="([^"]*)"', text, re.I)
	desc = dm.group(1) if dm else ""  # already HTML-escaped (from source attr)
	t = html.escape(title)
	tags = (
		f'<meta property="og:title" content="{t}">\n'
		'<meta property="og:type" content="article">\n'
		'<meta property="og:site_name" content="cache">\n'
		f'<meta property="og:url" content="{BASE_URL}/{rel_path}">\n'
		+ (f'<meta property="og:description" content="{desc}">\n' if desc else "")
		+ '<meta name="twitter:card" content="summary">\n'
		+ f'<meta name="twitter:title" content="{t} &mdash; cache">\n'
		+ (f'<meta name="twitter:description" content="{desc}">\n' if desc else "")
	)
	return re.sub(r'</head>', tags + "</head>", text, count=1, flags=re.I)


def build_sitemap():
	"""Write sitemap.xml listing every public page, anchored at BASE_URL.

	Deliberately absent: private.html and everything under private/ (the point
	is not to advertise them), and the /<slug>.html redirect stubs (a sitemap
	entry that immediately redirects is just noise to a crawler).
	"""
	paths = (
		["index.html", "reading.html", "standalone.html"]
		+ [post_url(slug) for slug in POSTS]
		+ [f"reading/{slug}/index.html" for slug, _cn, _l in READING]
		+ [target for target, _l in LOCAL_STANDALONE]
	)
	rows = "\n".join(f"  <url><loc>{BASE_URL}/{p}</loc></url>" for p in paths)
	xml = (
		'<?xml version="1.0" encoding="UTF-8"?>\n'
		'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
		f"{rows}\n</urlset>\n"
	)
	with open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8") as f:
		f.write(xml)


def build_robots():
	"""robots.txt. Private URLs are disallowed here *and* carry a noindex meta:
	the Disallow keeps polite crawlers out, the meta is what actually keeps a
	page out of an index if it gets linked from somewhere else."""
	lines = [
		"User-agent: *",
		"Allow: /",
		"Disallow: /_mirror/",
		"Disallow: /_private/",
		"Disallow: /private/",
		"Disallow: /private.html",
		"",
		f"Sitemap: {BASE_URL}/sitemap.xml",
		"",
	]
	with open(os.path.join(OUT, "robots.txt"), "w", encoding="utf-8") as f:
		f.write("\n".join(lines))


def page_description(path):
	"""<meta name=description> of a built page, or "" if it has none."""
	try:
		with open(path, encoding="utf-8") as f:
			text = f.read()
	except OSError:
		return ""
	m = re.search(r'<meta name="description" content="([^"]*)"', text, re.I)
	return html.unescape(m.group(1)) if m else ""


def build_feed():
	"""Regenerate feed.xml from the same lists that drive everything else.

	It used to be maintained by hand and had drifted: still advertising the old
	/<slug>.html post URLs, and missing every reading article added since it was
	last touched. Private posts are never included — a feed is a broadcast.

	Moving the posts does change their guids, so subscribers will see the twelve
	cache posts once more. The alternative, keeping the feed pointed at the old
	URLs, would route every reader through a redirect forever.
	"""
	def item(title, path, desc, iso=""):
		url = f"{BASE_URL}/{path}"
		pub = ""
		if iso:
			dt = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
			pub = f"      <pubDate>{dt.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>\n"
		return (
			"    <item>\n"
			f"      <title>{html.escape(title)}</title>\n"
			f"      <link>{url}</link>\n"
			f'      <guid isPermaLink="true">{url}</guid>\n'
			+ pub
			+ f"      <description>{html.escape(desc)}</description>\n"
			"    </item>"
		)

	items, latest = [], ""
	for slug in POSTS:
		title, iso, _disp = extract_meta(slug)
		items.append(item(title, post_url(slug),
		                  page_description(os.path.join(SRC, f"{slug}.html")), iso))
		latest = max(latest, iso)
	for slug, _cn, label in READING:
		items.append(item(
			label, f"reading/{slug}/index.html",
			page_description(os.path.join(OUT, "reading", slug, "index.html")),
		))

	# Stamped from the newest post rather than "now", so an unchanged site
	# rebuilds to a byte-identical feed instead of showing up in every diff.
	built = datetime.datetime.strptime(latest, "%Y-%m-%dT%H:%M:%SZ").strftime(
		"%a, %d %b %Y %H:%M:%S +0000") if latest else ""
	xml = (
		'<?xml version="1.0" encoding="UTF-8"?>\n'
		'<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
		"  <channel>\n"
		"    <title>cache</title>\n"
		f"    <link>{BASE_URL}/</link>\n"
		"    <description>Benson Wang&#39;s blog and reading room: essays and "
		"interactive, data-driven articles.</description>\n"
		"    <language>en</language>\n"
		f'    <atom:link href="{BASE_URL}/feed.xml" rel="self" '
		'type="application/rss+xml" />\n'
		+ (f"    <lastBuildDate>{built}</lastBuildDate>\n" if built else "")
		+ "\n".join(items)
		+ "\n  </channel>\n</rss>\n"
	)
	with open(os.path.join(OUT, "feed.xml"), "w", encoding="utf-8") as f:
		f.write(xml)

# Reverse-chronological order (newest first), matching the original homepage feed.
POSTS = [
    "token-playbook",
    "some-projects",
    "practical-poker",
    "ecom-experiments",
    "why-crypto",
    "growing-peppers",
    "book-reviews",
    "wasted-time",
    "trading-automation",
    "api-in-rust",
    "cicd-on-gcp",
    "nomad-and-waypoint",
]

# Display titles for the cache posts, recased to Title Case so they match the
# reading articles (the Write.as sources ship all-lowercase). Kept concise —
# same words, just the casing + acronyms. Applied to the post page, homepage
# list, tray, and <title> tag. Keyed by slug.
TITLE_OVERRIDES = {
    "token-playbook": "Token Playbook",
    "some-projects": "Some Projects",
    "practical-poker": "Practical Poker",
    "ecom-experiments": "Ecom Experiments",
    "why-crypto": "Why Crypto",
    "growing-peppers": "Growing Peppers",
    "book-reviews": "Book Reviews",
    "wasted-time": "Dumb Poker",
    "trading-automation": "Trading Automation",
    "api-in-rust": "API in Rust",
    "cicd-on-gcp": "CI/CD on GCP + SQL",
    "nomad-and-waypoint": "Nomad & Waypoint",
}

# Every reading article, ordered newest edit first — this order drives the
# navigator tray, the homepage feed, and sitemap.xml. Keep it sorted by when
# each article was last meaningfully edited: new or freshly revised ones go on
# top. (slug, codename, display title).
#
# The codename is the GitHub Pages project the article was mirrored from
# (www.bwang.io/<codename>/), and it doubles as the build marker:
#   codename set  -> mirrored; rebuilt from _mirror/reading/<slug>.html every
#                    run, so never hand-edit reading/<slug>/index.html.
#   codename None -> authored directly in reading/<slug>/index.html with no
#                    mirror source. Never regenerated (that would discard the
#                    hand-written markup); only its navigator tray is refreshed
#                    in place, so reordering this list still reaches it.
READING = [
	("smartphone-addiction", None, "Predicting Smartphone Addiction"),
	("kaggriculture", None, "Improving Kaggriculture Bot"),
	("iran-war", None, "The Iran War"),
	("kimi-vs-claude", None, "Open vs Closed Models"),
	("klefki", None, "Penetration Testing with Claude Code"),
	("world-cup-2026", "golem", "Who Will Win the 2026 World Cup?"),
	("poker-pros", "voltorb", "High Roller Ledger"),
	("spacs", "jolteon", "Understanding SPACs"),
	("ipos-spacex", "elekid", "Will the SpaceX IPO Beat the Market?"),
	("making-an-iphone", "electabuzz", "Anatomy of an iPhone"),
	("watches", "magnemite", "Watches That Beat Retail"),
	("wine", "squirtle", "Wine as an Investment Asset"),
	("real-estate", "arbok", "What Predicts US Real-Estate Returns?"),
	("ncaa", "omastar", "Predicting March Madness 2026"),
]
# Derived from READING so the two can never drift apart.
MIRRORED_READING = [e for e in READING if e[1] is not None]
NATIVE_READING = [e for e in READING if e[1] is None]
# Full-screen interactive apps that can't live in the narrow reading column (a
# live chat app and a multi-page trading terminal). Listed under their own
# "standalone" tab in the navigator, and built the same way as reading articles.
# Mirrored standalone apps (built locally). Empty now — the interactive apps are
# all linked out to their live versions instead (see EXTERNAL_STANDALONE).
STANDALONE = []
# Apps in the standalone feed, ordered newest edit first (same convention as
# READING). Two kinds, distinguished by "local":
#   local True  -> built into this archive and served from this domain, so it
#                  gets an ordinary same-tab link resolved relative to the page.
#   local False -> a live, dynamic app that can't be frozen into a static
#                  archive; linked out to its running version in a new tab.
# (target, label, local). Targets for local apps are repo-root-relative dirs.
STANDALONE_APPS = [
	("whismur/", "Tone Skill Builder", True),
	("https://www.bwang.io/ekans/", "Trading Signals", False),
	("https://www.bwang.io/magikarp/", "Newsletter", False),
	("https://www.bwang.io/muk/", "Energy Trading Primer", False),
	("https://chansey.bwang.io", "Medical RAG", False),
	("https://arbitrage.bwang.io", "Arbitrage Finder", False),
	("https://stonks.bwang.io/", "Stock Picker", False),
]
# Kept as a derived view: sitemap + build stats only care about the local ones.
LOCAL_STANDALONE = [(t, l) for t, l, local in STANDALONE_APPS if local]
EXTERNAL_STANDALONE = [(t, l) for t, l, local in STANDALONE_APPS if not local]
# Every reading article now shares the cache narrow column for a consistent
# format. The standalone apps keep their own full-bleed layout.
NARROW_SLUGS = {slug for slug, _cn, _label in READING}
# Display titles of the cache (blog) posts, filled in by main() before any page
# is built — used to populate the left tray.
CACHE_ITEMS: list[tuple[str, str]] = []

# Permanent floating list of posts (top-left card), shown by default and
# minimizable to a small pill. Checkbox-driven (no JS) so the collapse animates.
# Opting every page into the View Transitions API (in TRAY_STYLE + inside.css)
# makes navigating to an article cross-fade in supporting browsers.
# Extra <style> shipped only with reading-article pages (they don't load
# inside.css): Josefin Sans for the drawer UI + a fade-in entrance on load.
READING_EXTRA = (
	"<style>"
	"@font-face{{font-family:'Josefin Sans';font-style:normal;font-weight:400;"
	"src:url('{p}/fonts/inside/josefin-sans-v15-latin-regular.woff2') format('woff2');}}"
	"@font-face{{font-family:'Josefin Sans';font-style:normal;font-weight:600;"
	"src:url('{p}/fonts/inside/josefin-sans-v15-latin-600.woff2') format('woff2');}}"
	"@keyframes cacheFadeIn{{from{{opacity:0;}}to{{opacity:1;}}}}"
	"body{{animation:cacheFadeIn .4s ease both;}}"
	"</style>"
)

TRAY_STYLE = """<style>
@view-transition{navigation:auto;}
.nav-float{position:fixed;top:22px;left:22px;z-index:2147483647;pointer-events:none;
	font:400 14px/1.45 'Josefin Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}
.nav-min-cb{position:absolute;width:0;height:0;opacity:0;pointer-events:none;}
.nav-card{width:230px;max-height:calc(100vh - 44px);overflow-y:auto;
	background:rgba(255,255,255,.82);-webkit-backdrop-filter:blur(14px) saturate(1.5);
	backdrop-filter:blur(14px) saturate(1.5);border:1px solid rgba(140,140,140,.16);
	border-radius:13px;padding:14px 0 16px;pointer-events:auto;transform-origin:top left;
	transition:opacity .24s ease,transform .24s ease;}
.nav-head{display:flex;align-items:center;justify-content:space-between;padding:0 16px 8px;}
.nav-home{display:inline-flex;align-items:center;color:#9a9a9a;text-decoration:none;
	padding:2px;transition:color .15s;}
.nav-home:hover{color:#333;}
.nav-mini{cursor:pointer;color:#c4c4c4;font-size:21px;line-height:.5;padding:0 3px 6px;
	user-select:none;transition:color .15s;}
.nav-mini:hover{color:#333;}
.nav-restore{position:absolute;top:0;left:0;display:inline-flex;align-items:center;gap:8px;
	cursor:pointer;background:rgba(255,255,255,.82);-webkit-backdrop-filter:blur(14px) saturate(1.5);
	backdrop-filter:blur(14px) saturate(1.5);border:1px solid rgba(140,140,140,.2);
	color:#555;border-radius:11px;padding:8px 14px;font-size:13px;user-select:none;
	opacity:0;pointer-events:none;transition:opacity .2s ease;}
.nav-restore::before{content:"";width:15px;height:11px;flex:none;color:#888;
	background:linear-gradient(currentColor,currentColor) left top/100% 1.5px no-repeat,
		linear-gradient(currentColor,currentColor) left center/100% 1.5px no-repeat,
		linear-gradient(currentColor,currentColor) left bottom/100% 1.5px no-repeat;}
.nav-restore:hover{color:#111;}
.nav-min-cb:checked ~ .nav-card{opacity:0;transform:scale(.96) translateY(-6px);pointer-events:none;}
.nav-min-cb:checked ~ .nav-restore{opacity:1;pointer-events:auto;}
.nav-card a.item{display:block;padding:7px 20px;color:#333;text-decoration:none;
	white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.nav-card a.item:hover{background:#f6f6f6;color:#111;}
.nav-card a.item.active{color:#357BB3;font-weight:600;box-shadow:inset 2px 0 0 #357BB3;}
.nav-radio{position:absolute;opacity:0;pointer-events:none;}
.nav-toggle{display:flex;flex-wrap:wrap;gap:.5rem .9rem;margin:0 20px 12px;}
.nav-toggle label{font-size:13px;font-weight:600;color:#c4c4c4;cursor:pointer;
	padding:0 0 5px;border-bottom:2px solid transparent;user-select:none;}
.nav-card #nav-cache:checked ~ .nav-toggle label[for=nav-cache],
.nav-card #nav-reading:checked ~ .nav-toggle label[for=nav-reading],
.nav-card #nav-standalone:checked ~ .nav-toggle label[for=nav-standalone],
.nav-card #nav-private:checked ~ .nav-toggle label[for=nav-private]{
	color:#111;border-bottom-color:#357BB3;}
.nav-feed{display:none;}
.nav-card #nav-cache:checked ~ .nf-cache{display:block;}
.nav-card #nav-reading:checked ~ .nf-reading{display:block;}
.nav-card #nav-standalone:checked ~ .nf-standalone{display:block;}
.nav-card #nav-private:checked ~ .nf-private{display:block;}
/* The private feed lists nothing until the browser has decrypted it, so the
   tray entry is a padlocked link to the locked index rather than titles. */
.nav-card a.item.locked{color:#8a8a8a;font-style:italic;}
.nav-card a.item.locked::before{content:"\\1F512\\FE0E";font-style:normal;margin-right:6px;opacity:.55;}
/* The panel is a left rail beside the centered column. Until the viewport is
   wide enough for it to clear that column (same breakpoint as the article
   outline), start it minimized: the pill shows by default and tapping it
   expands the list. Otherwise the card slides out over the post text. */
@media (max-width:1330px){
	.nav-card{opacity:0;transform:scale(.96) translateY(-6px);pointer-events:none;}
	.nav-restore{opacity:1;pointer-events:auto;}
	.nav-min-cb:checked ~ .nav-card{opacity:1;transform:none;pointer-events:auto;}
	.nav-min-cb:checked ~ .nav-restore{opacity:0;pointer-events:none;}
}
@media (max-width:700px){
	.nav-card{width:min(230px,calc(100vw - 36px));}
	/* Phones have no side gutter for the pill to live in, so the fixed
	   "posts" control landed on top of the first line of every headline.
	   Tuck it into the corner and reserve the strip it occupies. The
	   :has() guard keeps the reserved space off pages with no tray (the
	   homepage, standalone apps); doubling it out-specifies the theme's
	   own !important body padding. */
	.nav-float{top:12px;left:12px;}
	html body:has(.nav-float):has(.nav-float){padding-top:56px!important;}
	/* Plotly's zoom/pan/export bar is absolutely positioned past the right
	   edge of a phone-width plot and was the one thing on the whole site
	   forcing a horizontal scroll. It is a mouse affordance anyway. */
	.js-plotly-plot .modebar{display:none!important;}
	/* Grid and flex items default to min-width:auto, so a tile wider than its
	   track refuses to shrink and pushes the page sideways instead. Let the
	   tile rows shrink, and drop the supplier grid to one column. */
	.stats,.suppliers-grid,.headrow,.flow{min-width:0;}
	.stats>*,.suppliers-grid>*,.headrow>*,.flow>*{min-width:0;}
	.suppliers-grid{grid-template-columns:1fr;}
}
@media (prefers-reduced-motion: reduce){
	.nav-card,.nav-restore{transition:none;}
}
</style>"""


def tray_html(context, active_slug=None):
	"""Left-drawer tray listing the home link + every post (cache + reading).

	`context` says where the page sits, which fixes both the relative link
	prefixes and which feed tab opens by default: "root" for the top-level feed
	pages, or "cache" / "reading" / "private" for a post one directory deep.

	Note what the private feed does *not* contain: this tray is baked into every
	public page, so listing private titles here would publish exactly what the
	encryption is protecting. It gets a single link to the locked index instead,
	and the real list is decrypted in the browser.
	"""
	standalone_slugs = {slug for slug, _cn, _label in STANDALONE}
	up = "" if context == "root" else "../../"
	home = f"{up}index.html"
	read_href = f"{up}reading/{{}}/index.html".format
	cache_href = f"{up}{POST_DIR}/{{}}/index.html".format
	local_href = f"{up}{{}}".format
	private_href = f"{up}private.html"

	# Default the toggle to the feed holding the current page.
	open_feed = context if context in ("cache", "reading", "private") else "cache"
	if context == "reading" and active_slug in standalone_slugs:
		open_feed = "standalone"
	checked = {name: " checked" if name == open_feed else ""
	           for name in ("cache", "reading", "standalone", "private")}
	# Reading articles don't load inside.css, so ship Josefin Sans + entrance anim.
	face = READING_EXTRA.format(p="../../assets") if context == "reading" else ""

	def item(href, label, slug):
		cls = "item active" if slug == active_slug else "item"
		return f'<a class="{cls}" href="{href}">{html.escape(label)}</a>'

	cache_items = "".join(item(cache_href(slug), title, slug) for slug, title in CACHE_ITEMS)
	reading_items = "".join(item(read_href(slug), label, slug) for slug, _cn, label in READING)
	standalone_items = "".join(
		item(read_href(slug), label, slug)
		for slug, _cn, label in STANDALONE
	) + "".join(
		# One ordered pass so local and external apps interleave by recency.
		item(local_href(target), label, None) if local
		else external_anchor(target, label, "item ext")
		for target, label, local in STANDALONE_APPS
	)
	private_items = f'<a class="item locked" href="{private_href}">unlock private posts</a>'
	return (
		face
		+ TRAY_STYLE
		+ '<div class="nav-float">'
		+ '<input type="checkbox" id="nav-min" class="nav-min-cb" aria-label="Minimize post list">'
		+ '<label class="nav-restore" for="nav-min" title="Show posts">posts</label>'
		+ '<div class="nav-card">'
		+ '<div class="nav-head">'
		+ f'<a class="nav-home" href="{home}" title="Home" aria-label="Home">'
		+ '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" '
		+ 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
		+ '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h13V10"/></svg></a>'
		+ '<label class="nav-mini" for="nav-min" title="Minimize" aria-label="Minimize">–</label>'
		+ '</div>'
		+ f'<input type="radio" name="nav-feed" id="nav-cache" class="nav-radio"{checked["cache"]}>'
		+ f'<input type="radio" name="nav-feed" id="nav-reading" class="nav-radio"{checked["reading"]}>'
		+ f'<input type="radio" name="nav-feed" id="nav-standalone" class="nav-radio"{checked["standalone"]}>'
		+ f'<input type="radio" name="nav-feed" id="nav-private" class="nav-radio"{checked["private"]}>'
		+ '<div class="nav-toggle"><label for="nav-cache">cache</label>'
		+ '<label for="nav-reading">reading</label>'
		+ '<label for="nav-standalone">standalone</label>'
		+ '<label for="nav-private">private</label></div>'
		+ f'<div class="nav-feed nf-cache">{cache_items}</div>'
		+ f'<div class="nav-feed nf-reading">{reading_items}</div>'
		+ f'<div class="nav-feed nf-standalone">{standalone_items}</div>'
		+ f'<div class="nav-feed nf-private">{private_items}</div>'
		+ '</div>'
		+ '</div>'
	)


def inject_tray(text, context, active_slug=None):
	"""Insert the tray immediately after the opening <body> tag.

	Anchor on </head> + <body> rather than a bare <body>: some articles mention
	the literal text "<body>" inside a CSS comment in their <head> (e.g.
	real-estate), and a bare-<body> regex would match that first and inject the
	tray inside the stylesheet."""
	tray = tray_html(context, active_slug)
	new, n = re.subn(
		r'(</head>\s*<body\b[^>]*>)',
		lambda m: m.group(1) + "\n" + tray, text, count=1, flags=re.I,
	)
	if n == 0:  # fall back to the first real <body> tag
		new = re.sub(r'(<body\b[^>]*>)', lambda m: m.group(1) + "\n" + tray, text, count=1, flags=re.I)
	return new

# The whole site is styled by a local adaptation of the Typora "Inside" theme.
# `up` is the hop back to the site root ("" for the feed pages at the root,
# "../../" for anything under cache/, reading/ or private/).
def theme_link(up=""):
	return f'<link rel="stylesheet" type="text/css" href="{up}assets/css/inside.css" />'

# Plays a lite-YouTube facade inline when served over http(s); from a file://
# preview it lets the anchor open the video on YouTube instead (Error 153 there).
YT_SCRIPT = """\t<script id="yt-lite-script">
	document.addEventListener('click', function (e) {
		var a = e.target.closest('.yt-lite');
		if (!a) return;
		if (location.protocol === 'file:') return;  // let it open on YouTube
		e.preventDefault();
		var f = document.createElement('iframe');
		f.className = 'yt-frame';
		f.setAttribute('allow', 'autoplay; fullscreen; encrypted-media; picture-in-picture');
		f.setAttribute('allowfullscreen', '');
		f.src = 'https://www.youtube-nocookie.com/embed/' + a.dataset.id + '?autoplay=1';
		a.replaceWith(f);
	}, false);
	</script>"""


def rewrite_common(text, up=""):
	"""Asset + link rewrites shared by every page.

	`up` is the relative hop from the page back to the site root: "" for the
	feed pages, "../../" for a post at cache/<slug>/index.html.
	"""
	# Replace the Write.as theme stylesheet with our local Inside theme.
	text = text.replace(
		'<link rel="stylesheet" type="text/css" '
		'href="https://cdn.writeas.net/css/write.7a8d594726b6871de2afc.css" />',
		theme_link(up),
	)
	# Local snap.as images
	text = re.sub(r"https://i\.snap\.as/([A-Za-z0-9]+\.png)", rf"{up}assets/img/\1", text)
	# Drop the RSS alternate <link> (no feed on the archive)
	text = re.sub(r'\s*<link rel="alternate"[^>]*?/>\n?', "\n", text)
	# Write.as paginated the collection; this archive doesn't, so the inherited
	# <link rel="next" href="/page/2"> pointed at a page that never existed here.
	text = re.sub(r'\s*<link rel="next"[^>]*?>\n?', "\n", text)
	# Remove the write.as follow iframe embed if present
	text = re.sub(r'<iframe[^>]*write\.as/me/iframe[^>]*>.*?</iframe>', "", text, flags=re.S)
	text = re.sub(r'<p>\s*<iframe[^>]*write\.as/me/iframe[^>]*>\s*</iframe>\s*</p>', "", text, flags=re.S)
	# Replace Embedly's YouTube iframes with a click-to-play "lite" facade.
	# Live YouTube iframes refuse to play from a file:// (null) origin, and the
	# original //cdn.embedly.com wrapper was protocol-relative. The facade shows
	# a self-hosted poster everywhere, plays inline when served over http(s),
	# and falls back to opening the video on YouTube from file://.
	text = re.sub(
		r'<iframe\b[^>]*?youtube\.com%2Fembed%2F([A-Za-z0-9_-]+)[^>]*?>\s*</iframe>',
		lambda m: (
			'<a class="yt-lite" target="_blank" rel="noopener" '
			f'href="https://www.youtube.com/watch?v={m.group(1)}" '
			f'data-id="{m.group(1)}" '
			f'style="background-image:url(\'{up}assets/img/yt/{m.group(1)}.jpg\')">'
			'<span class="yt-play"></span></a>'
		),
		text,
		flags=re.S,
	)
	# Inject the tiny play-on-click script once, if the page has any facades.
	if 'class="yt-lite"' in text and "yt-lite-script" not in text:
		text = text.replace("</body>", YT_SCRIPT + "\n\t</body>", 1)
	# Drop the "reading" and "about" tabs from the header nav (reading is merged
	# into the homepage list now; the about page has been removed entirely).
	text = re.sub(
		r'<a class="pinned" href="https?://cache\.bwang\.io/(reading|about)">(reading|about)</a>',
		"",
		text,
	)
	# Cross-post links. build_post() rewrites canonical/og:url to absolute URLs
	# before calling this, and those rewritten values no longer contain the bare
	# ".../<slug>" form matched here, so they survive untouched.
	for slug in POSTS:
		text = text.replace(f"https://cache.bwang.io/{slug}", f"{up}{post_url(slug)}")
	# Any leftover feed link -> homepage
	text = text.replace("https://cache.bwang.io/feed/", f"{up}index.html")
	# Root / blog-title links -> index.html
	text = re.sub(r'href="https?://cache\.bwang\.io/"', f'href="{up}index.html"', text)
	text = re.sub(r'href="https?://cache\.bwang\.io"', f'href="{up}index.html"', text)
	# blog-title and author links use href="/"
	text = text.replace('href="/" class="h-card', f'href="{up}index.html" class="h-card')
	text = text.replace('rel="author" href="/"', f'rel="author" href="{up}index.html"')
	# One shared favicon on every page (cache posts + homepage).
	text = set_favicon(text)
	# Analytics on every page.
	text = inject_ga(text)
	return text


def build_post(slug):
	with open(os.path.join(SRC, f"{slug}.html"), encoding="utf-8") as f:
		text = f.read()
	# Pin canonical + og:url to the post's absolute URL before the generic link
	# rewrite below turns every other mention of it into a relative path. A
	# relative canonical works but says less, and og:url has to be absolute to
	# be useful to anything that unfurls the link.
	abs_url = f"{BASE_URL}/{post_url(slug)}"
	text = re.sub(
		r'(<link rel="canonical" href=")https?://cache\.bwang\.io/' + re.escape(slug) + r'(")',
		lambda m: m.group(1) + abs_url + m.group(2), text, count=1)
	text = re.sub(
		r'(<meta property="og:url" content=")https?://cache\.bwang\.io/' + re.escape(slug) + r'(")',
		lambda m: m.group(1) + abs_url + m.group(2), text, count=1)
	text = rewrite_common(text, up="../../")
	# Recase the post title (visible <h2> + browser <title>) to match reading.
	new_title = TITLE_OVERRIDES.get(slug)
	if new_title:
		text = re.sub(
			r'(<h2 id="title"[^>]*>).*?(</h2>)',
			lambda m: m.group(1) + html.escape(new_title) + m.group(2),
			text, count=1, flags=re.S,
		)
		text = re.sub(
			r'(<title>).*?(</title>)',
			lambda m: m.group(1) + html.escape(new_title) + " &mdash; cache" + m.group(2),
			text, count=1, flags=re.S,
		)
		# Keep the social-card titles in sync with the recased title.
		esc = html.escape(new_title)
		text = re.sub(r'(<meta property="og:title" content=")[^"]*(")',
			lambda m: m.group(1) + esc + m.group(2), text, count=1)
		text = re.sub(r'(<meta name="twitter:title" content=")[^"]*(")',
			lambda m: m.group(1) + esc + " &mdash; cache" + m.group(2), text, count=1)
	text = inject_tray(text, "cache", slug)
	text = inject_backtotop(text)
	out_dir = os.path.join(OUT, POST_DIR, slug)
	os.makedirs(out_dir, exist_ok=True)
	with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
		f.write(text)


REDIRECT_MARK_START = "<!-- moved-posts:start -->"
REDIRECT_MARK_END = "<!-- moved-posts:end -->"

REDIRECT_SCRIPT = """{start}
<script>
/* Generated by build.py — edit build_redirects(), not this block.
   Posts used to live at /<slug>.html. Those paths no longer exist, so Pages
   serves this page for them; map the known ones to their new home. */
(function () {{
	var moved = {slugs};
	var m = location.pathname.match(/^\\/([A-Za-z0-9_-]+)\\.html$/);
	if (!m || moved.indexOf(m[1]) === -1) return;
	location.replace("/{dir}/" + m[1] + "/index.html" + location.search + location.hash);
}})();
</script>
{end}"""


def build_redirects():
	"""Keep the pre-move URLs working, without cluttering the site root.

	Posts used to live at /<slug>.html and those links are out in the world —
	in the RSS feed readers already hold, in search results, in anything anyone
	bookmarked. GitHub Pages has no redirect config, and the obvious static
	substitute — one stub file per post at the old path — puts a dozen files
	back in the root, which is what moving the posts into cache/ was meant to
	fix. Pages does serve 404.html for any path it can't resolve, so the
	forwarding lives there instead: one generated block, no root clutter.

	The tradeoff is the status code. A stub answered 200 and carried a
	rel=canonical that search engines follow; this answers 404 before the
	redirect runs, so crawlers treat the old URLs as gone and only real
	browsers get forwarded. That is the right trade here — the old paths were
	only live for a couple of months, sitemap.xml and feed.xml have pointed at
	the cache/ URLs since the move, and readers with a stale link still land on
	the post.
	"""
	path = os.path.join(OUT, "404.html")
	with open(path, encoding="utf-8") as f:
		page = f.read()
	block = REDIRECT_SCRIPT.format(
		start=REDIRECT_MARK_START, end=REDIRECT_MARK_END, dir=POST_DIR,
		slugs=json.dumps(sorted(POSTS), separators=(",", ":")),
	)
	pattern = re.compile(
		re.escape(REDIRECT_MARK_START) + ".*?" + re.escape(REDIRECT_MARK_END),
		re.S,
	)
	if pattern.search(page):
		page = pattern.sub(lambda _: block, page, count=1)
	else:
		# First run against a 404.html that predates the move: drop the block in
		# at the top of <head> so it redirects before the page paints.
		page = re.sub(r'(<head>)', lambda m: m.group(1) + "\n" + block,
		              page, count=1, flags=re.I)
	with open(path, "w", encoding="utf-8") as f:
		f.write(page)


def build_reading_articles():
	"""Mirror each reading article into reading/<slug>/index.html, preserving its
	original styling. Copy any sibling assets and inject a back-link."""
	src_dir = os.path.join(SRC, "reading")
	for slug, codename, _label in MIRRORED_READING + STANDALONE:
		with open(os.path.join(src_dir, f"{slug}.html"), encoding="utf-8") as f:
			text = f.read()
		# Unify the browser tab title to the cache format: "<Title> — cache".
		text = re.sub(
			r'(<title>).*?(</title>)',
			lambda m: m.group(1) + html.escape(_label) + " &mdash; cache" + m.group(2),
			text, count=1, flags=re.S | re.I,
		)
		# Re-theme to the cache look (Josefin Sans + narrow column): load the
		# override stylesheet last in <head> so its !important rules win.
		theme_link = (
			'<link rel="stylesheet" type="text/css" '
			'href="../../assets/css/reading-theme.css">'
		)
		text = re.sub(r'</head>', theme_link + "\n</head>", text, count=1, flags=re.I)
		# Text essays get the narrow cache column (via <html class>). The wider
		# articles (dashboards + the two with their own in-page TOC) instead keep
		# the posts tray collapsed to its pill by default, so it never covers
		# their left-aligned content/nav — open it on demand from the pill.
		html_class = "cache-narrow" if slug in NARROW_SLUGS else "nav-collapsed"
		if re.search(r'<html\b[^>]*\sclass=', text, flags=re.I):
			text = re.sub(r'(<html\b[^>]*\sclass=")', r'\1' + html_class + ' ', text,
					count=1, flags=re.I)
		else:
			text = re.sub(r'(<html\b)', r'\1 class="' + html_class + '"', text,
					count=1, flags=re.I)
		# Move the kicker to directly under the title, like the cache posts' date
		# line: swap <div class="kick">…</div> with the <h1> right after it.
		if slug in NARROW_SLUGS:
			text = re.sub(
				r'(<div class=["\']?kick["\']?[^>]*>.*?</div>)(\s*)(<h1\b[^>]*>.*?</h1>)',
				r'\3\2\1',
				text, count=1, flags=re.S | re.I,
			)
		# Shared favicon + analytics + consistent Open Graph tags + back-to-top.
		text = set_favicon(text)
		text = inject_ga(text)
		text = add_og_tags(text, _label, f"reading/{slug}/index.html")
		# Inject the left tray right after <body ...>, highlighting this article.
		text = inject_tray(text, "reading", slug)
		if slug in NARROW_SLUGS:
			text = inject_backtotop(text)

		out_dir = os.path.join(OUT, "reading", slug)
		os.makedirs(out_dir, exist_ok=True)
		with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
			f.write(text)
		# Copy sibling assets + runtime data (styles.css, app.js, data/*.json,
		# pipeline/*.json, …), preserving any nested subdirectories.
		asset_dir = os.path.join(src_dir, "assets", slug)
		if os.path.isdir(asset_dir):
			for root, _dirs, files in os.walk(asset_dir):
				rel = os.path.relpath(root, asset_dir)
				dest = out_dir if rel == "." else os.path.join(out_dir, rel)
				os.makedirs(dest, exist_ok=True)
				for name in files:
					with open(os.path.join(root, name), "rb") as fin:
						data = fin.read()
					with open(os.path.join(dest, name), "wb") as fout:
						fout.write(data)


def retray_native_reading():
	"""Refresh only the navigator tray inside each natively-authored article.

	These have no _mirror source, so they can't be regenerated — the built file
	IS the source. Swapping the TRAY_STYLE + <div class="nav-float"> pair keeps
	their hand-written markup intact while still picking up list reordering, new
	entries, and tray CSS changes.

	The style block has to be swapped alongside the markup: it carries the tray's
	own responsive rules, so refreshing only the <div> would leave these articles
	pinned to whatever CSS shipped the day they were written. TRAY_STYLE's
	@view-transition line is the anchor — it opens that block and appears
	nowhere else. The preceding READING_EXTRA block (fonts, fade-in) is
	order-independent and left alone."""
	anchor = r'<style>\s*@view-transition\{navigation:auto;\}'
	for slug, _cn, _label in NATIVE_READING:
		path = os.path.join(OUT, "reading", slug, "index.html")
		if not os.path.isfile(path):
			print(f"  warning: {path} missing, skipping tray refresh")
			continue
		with open(path, encoding="utf-8") as f:
			text = f.read()
		tray = re.search(
			anchor + r'.*?<div class="nav-feed nf-standalone">.*?</div></div></div>',
			text, flags=re.S,
		)
		if not tray:
			print(f"  warning: no tray found in {path}, skipping")
			continue
		fresh = re.search(
			anchor + r'.*', tray_html("reading", slug), flags=re.S,
		).group(0)
		with open(path, "w", encoding="utf-8") as f:
			f.write(text[: tray.start()] + fresh + text[tray.end() :])


def extract_meta(slug):
	"""Pull display title + published date from a post page."""
	with open(os.path.join(SRC, f"{slug}.html"), encoding="utf-8") as f:
		text = f.read()
	tm = re.search(r'<h2 id="title"[^>]*>(.*?)</h2>', text, re.S)
	title = html.unescape(re.sub(r"<[^>]+>", "", tm.group(1)).strip()) if tm else slug
	title = TITLE_OVERRIDES.get(slug, title)
	dm = re.search(r'<time class="dt-published"[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>', text, re.S)
	iso = dm.group(1) if dm else ""
	disp = dm.group(2).strip() if dm else ""
	return title, iso, disp


# One static page per feed, so the URL always names the tab you are looking at:
# / for cache, /reading.html, /standalone.html, /private.html. The tabs are
# ordinary links rather than the old hidden-radio toggle — still no JavaScript
# on the three public feeds, but every view is shareable and bookmarkable, the
# back button works, and search engines can index each list. The
# @view-transition rule in TRAY_STYLE animates the swap, so it still feels like
# an in-page toggle. (name, filename, <title>).
FEEDS = [
	("cache", "index.html", "cache"),
	("reading", "reading.html", "cache — reading"),
	("standalone", "standalone.html", "cache — standalone"),
	("private", "private.html", "cache — private"),
]


def feed_tabs(current):
	"""The cache tab points at "./" so the default view keeps the bare
	https://cache.bwang.io/ URL rather than /index.html."""
	return "".join(
		f'<a href="{"./" if fn == "index.html" else fn}"'
		f'{" class=active" if fn == current else ""}>{n}</a>'
		for n, fn, _t in FEEDS
	)


def index_template():
	"""(head, foot) lifted from the mirrored homepage, so every feed page keeps
	the real header, footer and styles."""
	with open(os.path.join(SRC, "index.html"), encoding="utf-8") as f:
		tpl = f.read()
	tpl = rewrite_common(tpl)
	head = tpl[: tpl.index("<section")]
	# Footer: from the real footer tag onward. The feed pages list posts but show
	# no video, so drop the lite-YouTube script that rewrite_common injected.
	foot = tpl[tpl.index("<footer") :]
	foot = re.sub(r'\t*<script id="yt-lite-script">.*?</script>\n?', "", foot, flags=re.S)
	return head, foot


def feed_page(head, foot, name, filename, title, inner, extra_head=""):
	"""Assemble and write one feed page."""
	body = (
		'<section id="wrapper">\n\n'
		+ f'<div class="feed-toggle">{feed_tabs(filename)}</div>\n'
		+ f'<div class="feed feed-{name}">\n' + inner + '\n</div>\n'
		+ '\n\t\t</section>\n\n\t\t'
	)
	page = head + body + foot
	if filename != "index.html":
		# Each feed is a distinct list, so each is its own canonical rather than
		# pointing back at the homepage.
		page = page.replace(
			'<link rel="canonical" href="index.html">',
			f'<link rel="canonical" href="{BASE_URL}/{filename}">',
		)
		page = page.replace("<title>cache</title>", f"<title>{title}</title>", 1)
		page = page.replace(
			'<meta property="og:title" content="cache" />',
			f'<meta property="og:title" content="{title}" />', 1,
		)
	if extra_head:
		page = re.sub(r'</head>', extra_head + "\n</head>", page, count=1, flags=re.I)
	with open(os.path.join(OUT, filename), "w", encoding="utf-8") as f:
		f.write(page)


def build_index():
	head, foot = index_template()

	# Cache posts (dated, reverse-chronological).
	cache_rows = []
	for slug in POSTS:
		title, iso, disp = extract_meta(slug)
		cache_rows.append(
			'<article class="norm h-entry">\n'
			f'\t<h2 class="post-title"><a href="{post_url(slug)}">{html.escape(title)}</a></h2>\n'
			f'\t<time class="dt-published" datetime="{iso}">{html.escape(disp)}</time>\n'
			'</article>'
		)
	# Reading articles + standalone apps — listed the same way (no date).
	def article_rows(items):
		rows = []
		for slug, _cn, label in items:
			rows.append(
				'<article class="norm h-entry">\n'
				f'\t<h2 class="post-title"><a href="reading/{slug}/index.html">{html.escape(label)}</a></h2>\n'
				'</article>'
			)
		return rows
	reading_rows = article_rows(READING)
	standalone_rows = article_rows(STANDALONE) + [
		'<article class="norm h-entry">\n'
		+ (
			f'\t<h2 class="post-title"><a href="{target}">{html.escape(label)}</a></h2>\n'
			if local
			else f'\t<h2 class="post-title">{external_anchor(target, label, "ext")}</h2>\n'
		)
		+ '</article>'
		for target, label, local in STANDALONE_APPS
	]

	rows_by_feed = {
		"cache": cache_rows, "reading": reading_rows, "standalone": standalone_rows,
	}
	for name, filename, title in FEEDS:
		if name == "private":  # built separately, from encrypted sources
			continue
		feed_page(head, foot, name, filename, title, "\n".join(rows_by_feed[name]))


# ------------------------------------------------------------- private feed
#
# The private posts are encrypted at build time and decrypted in the reader's
# browser, so the server (GitHub Pages) only ever holds ciphertext. That is the
# only kind of "private" a static site can actually offer: there is no backend
# to check a password against, so anything gated in JavaScript alone is gated
# only against people who don't open devtools.
#
# What this does and does not protect:
#   - Post bodies, titles and dates are AES-256-GCM ciphertext. Without the
#     passphrase they are not recoverable from the published files.
#   - The *existence* of the private feed is public, as is the number of posts
#     and roughly how long each one is. Slugs are inside the encrypted index, so
#     the per-post URLs aren't discoverable from the site itself.
#   - The passphrase is the whole security boundary and it is never stored
#     anywhere in the repo. Lose it and the posts are gone; there is no reset.
#
# Key derivation is PBKDF2-HMAC-SHA256 with a per-site random salt. The salt
# lives in _private/salt (git-ignored) and is reused across builds so an already
# unlocked browser session survives a rebuild.
PBKDF2_ITERS = 600_000
SALT_FILE = "salt"
# sessionStorage key holding the derived AES key, so unlocking the index also
# unlocks the posts you click through to, and a refresh doesn't re-prompt.
# Session-scoped: it's gone when the tab closes.
KEYSTORE = "cache.private.key"

PRIVATE_STYLE = """<style>
.lock{max-width:22rem;margin:2rem 0 3rem;}
.lock p{color:#757575;font-size:14px;margin:0 0 1rem;}
.lock form{display:flex;gap:.5rem;}
.lock input{flex:1;min-width:0;font:inherit;font-size:15px;padding:.5rem .7rem;
	border:1px solid #d8d8d8;border-radius:7px;background:#fff;color:#222;}
.lock input:focus{outline:none;border-color:#357BB3;}
.lock button{font:inherit;font-size:15px;font-weight:600;padding:.5rem 1.1rem;cursor:pointer;
	border:1px solid #357BB3;border-radius:7px;background:#357BB3;color:#fff;}
.lock button:hover{background:#2c6795;border-color:#2c6795;}
.lock button[disabled]{opacity:.55;cursor:default;}
.lock-msg{min-height:1.2em;margin:.8rem 0 0;font-size:14px;color:#757575;}
.lock-msg.error{color:#b3402f;}
</style>"""

# Shared client half of the scheme. The page defines renderVault(data) above
# this, and this drives the unlock: derive a key from the typed passphrase, try
# to decrypt, and treat a GCM authentication failure as "wrong passphrase" —
# no separate password check to get wrong.
PRIVATE_JS = """(function(){
	var V = JSON.parse(document.getElementById('vault').textContent);
	var form = document.getElementById('unlock-form');
	var msg = document.getElementById('unlock-msg');
	var lock = document.getElementById('lock');

	function bytes(s){ return Uint8Array.from(atob(s), function(c){ return c.charCodeAt(0); }); }
	function b64(buf){
		var b = new Uint8Array(buf), s = '';
		for (var i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
		return btoa(s);
	}
	function say(text, isError){
		msg.textContent = text;
		msg.classList.toggle('error', !!isError);
	}
	function derive(pass){
		return crypto.subtle.importKey('raw', new TextEncoder().encode(pass),
			'PBKDF2', false, ['deriveKey']).then(function(base){
			return crypto.subtle.deriveKey(
				{name:'PBKDF2', salt:bytes(V.salt), iterations:V.iters, hash:'SHA-256'},
				base, {name:'AES-GCM', length:256}, true, ['decrypt']);
		});
	}
	function open_(key){
		var raw = bytes(V.data);
		return crypto.subtle.decrypt({name:'AES-GCM', iv:raw.slice(0,12)}, key, raw.slice(12))
			.then(function(pt){ return JSON.parse(new TextDecoder().decode(pt)); });
	}
	function use(key){
		return open_(key).then(function(data){
			return crypto.subtle.exportKey('raw', key).then(function(raw){
				try { sessionStorage.setItem(V.store, b64(raw)); } catch (e) {}
				lock.hidden = true;
				renderVault(data);
			});
		});
	}

	form.addEventListener('submit', function(e){
		e.preventDefault();
		var btn = form.querySelector('button');
		btn.disabled = true;
		say('unlocking\\u2026');
		derive(form.pass.value).then(use).catch(function(){
			say('That passphrase does not open this.', true);
			form.pass.value = '';
			form.pass.focus();
		}).then(function(){ btn.disabled = false; });
	});

	// SubtleCrypto only exists in a secure context, so a file:// preview can't
	// decrypt anything. Say so rather than failing silently.
	if (!window.crypto || !crypto.subtle){
		form.hidden = true;
		say('Unlocking needs a secure context \\u2014 open this over https, or localhost.', true);
		return;
	}
	// Already unlocked earlier this session? Reuse the key and skip the prompt.
	var stored = null;
	try { stored = sessionStorage.getItem(V.store); } catch (e) {}
	if (stored){
		crypto.subtle.importKey('raw', bytes(stored), {name:'AES-GCM'}, true, ['decrypt'])
			.then(use)
			.catch(function(){ try { sessionStorage.removeItem(V.store); } catch (e) {} });
	}
})();"""

LOCK_HTML = """<div class="lock" id="lock">
<p>{blurb}</p>
<form id="unlock-form" autocomplete="off">
<input type="password" name="pass" placeholder="passphrase" aria-label="Passphrase" autofocus>
<button type="submit">unlock</button>
</form>
<p class="lock-msg" id="unlock-msg" role="status" aria-live="polite"></p>
</div>"""


def private_salt():
	"""Read the site's PBKDF2 salt, creating it on first run.

	Kept stable across builds on purpose: the browser caches the *derived* key
	for the session, and rotating the salt would invalidate it on every deploy.
	"""
	path = os.path.join(PRIVATE_SRC, SALT_FILE)
	if os.path.isfile(path):
		with open(path, encoding="utf-8") as f:
			return bytes.fromhex(f.read().strip())
	salt = secrets.token_bytes(16)
	with open(path, "w", encoding="utf-8") as f:
		f.write(salt.hex() + "\n")
	print(f"  created {os.path.relpath(path, ROOT)} (git-ignored — back it up)")
	return salt


def private_passphrase():
	"""Passphrase from the environment, or prompted for interactively."""
	p = os.environ.get("CACHE_PRIVATE_PASSPHRASE")
	if p:
		return p
	if sys.stdin.isatty():
		return getpass.getpass("Passphrase for the private feed: ") or None
	return None


def seal(key, obj):
	"""JSON -> base64(iv || ciphertext || tag), the layout the page's JS expects.

	The nonce is derived from the plaintext rather than drawn at random, so a
	post that hasn't changed re-encrypts to the same bytes and doesn't show up
	in every commit. That is a synthetic-IV construction, and it is safe for the
	reason random nonces are: what GCM cannot survive is one nonce covering two
	*different* plaintexts under the same key, and distinct plaintexts here get
	distinct nonces. Repeating a nonce for byte-identical input just reproduces
	the identical ciphertext, which leaks only that the post didn't change —
	something the commit history says anyway.
	"""
	plaintext = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
	nonce = hmac.new(key, plaintext, hashlib.sha256).digest()[:12]
	return base64.b64encode(nonce + aesgcm.encrypt(key, nonce, plaintext)).decode("ascii")


def vault_script(salt, payload):
	return (
		'<script id="vault" type="application/json">'
		+ json.dumps({
			"salt": base64.b64encode(salt).decode("ascii"),
			"iters": PBKDF2_ITERS,
			"store": KEYSTORE,
			"data": payload,
		}, separators=(",", ":"))
		+ "</script>"
	)


# Front matter: --- fenced for Markdown (the usual convention), an HTML comment
# for raw .html fragments. Both are just `key: value` lines.
_FRONT_MD = re.compile(r"\A﻿?---[ \t]*\n(.*?)\n---[ \t]*\n?", re.S)
_FRONT_HTML = re.compile(r"\A\s*<!--(.*?)-->\s*", re.S)
# Not posts: this directory's own README, the salt, and anything hidden.
PRIVATE_SKIP = {"readme.md", "readme.html", SALT_FILE}


def _front_matter(text, pattern):
	"""(metadata dict, remaining body)."""
	m = pattern.match(text)
	if not m:
		return {}, text
	meta = {}
	for line in m.group(1).splitlines():
		if ":" in line and not line.lstrip().startswith("#"):
			k, _, v = line.partition(":")
			meta[k.strip().lower()] = v.strip().strip('"').strip("'")
	return meta, text[m.end():]


def read_private_sources():
	"""Parse _private/<slug>.md into post dicts, newest first.

	    ---
	    title: What I Actually Think About It
	    date: 2026-08-13
	    ---

	    Body in **Markdown**.

	Both keys are optional. Without `title` the post takes its first `# heading`
	(the heading is then dropped from the body, since the page renders the title
	itself); without `date` it shows no date and sorts last.

	`.html` files still work for anything Markdown can't express, using an HTML
	comment for the front matter instead of the --- fence. Their contents are
	used as-is.
	"""
	if not os.path.isdir(PRIVATE_SRC):
		return []
	posts = []
	for name in sorted(os.listdir(PRIVATE_SRC)):
		slug, ext = os.path.splitext(name)
		if ext not in (".md", ".markdown", ".html") or name.startswith((".", "_")):
			continue
		if name.lower() in PRIVATE_SKIP:
			continue
		with open(os.path.join(PRIVATE_SRC, name), encoding="utf-8") as f:
			text = f.read()

		is_markdown = ext != ".html"
		meta, body = _front_matter(text, _FRONT_MD if is_markdown else _FRONT_HTML)
		title = meta.get("title")
		if is_markdown:
			# Always lift a leading H1 out of the body — the page template puts
			# the title above the content, so leaving it would print it twice.
			heading, body = markdown.first_heading(body)
			title = title or heading
			body = markdown.convert(body)
		iso = meta.get("date", "")
		try:
			disp = datetime.date.fromisoformat(iso).strftime("%B %-d, %Y")
		except ValueError:
			disp = iso
		posts.append({
			"slug": slug,
			"title": title or slug.replace("-", " "),
			"iso": iso,
			"date": disp,
			"html": body.strip(),
		})
	# Newest first; slug breaks ties so the order can't wobble between builds.
	posts.sort(key=lambda p: (p["iso"], p["slug"]), reverse=True)
	return posts


def build_private(head, foot):
	"""Write private.html plus one encrypted page per private post.

	Returns the number of posts sealed, or None if the private build was skipped
	(in which case any previously built pages are left exactly as they were —
	better a stale private feed than one silently emptied by a build on a
	machine that doesn't have the sources).
	"""
	posts = read_private_sources()
	head = head.replace(GA_TAG, "")  # no analytics beacons on the private feed
	noindex = '<meta name="robots" content="noindex, nofollow">'

	if not posts:
		if os.path.isdir(PRIVATE_SRC):
			print("  note: _private/ has no posts; writing an empty private feed")
		feed_page(
			head, foot, "private", "private.html", "cache — private",
			'<p style="color:#757575">No private posts yet.</p>',
			extra_head=noindex,
		)
		return 0

	passphrase = private_passphrase()
	if not passphrase:
		print("  warning: no passphrase (set CACHE_PRIVATE_PASSPHRASE); "
		      "leaving the private feed as-is")
		return None

	salt = private_salt()
	key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt,
	                          PBKDF2_ITERS, dklen=32)

	# The index: titles, dates and slugs together, encrypted as one blob. None
	# of it is in the page as plaintext, so the slugs stay unguessable too.
	index_payload = seal(key, {"posts": [
		{k: p[k] for k in ("slug", "title", "iso", "date")} for p in posts
	]})
	render_index = """<script>
function renderVault(v){
	var esc = function(s){ var d = document.createElement('div'); d.textContent = s; return d.innerHTML; };
	document.getElementById('private-list').innerHTML = v.posts.map(function(p){
		return '<article class="norm h-entry"><h2 class="post-title">'
			+ '<a href="private/' + encodeURIComponent(p.slug) + '/index.html">' + esc(p.title) + '</a>'
			+ '</h2>' + (p.date ? '<time class="dt-published" datetime="' + esc(p.iso) + '">'
			+ esc(p.date) + '</time>' : '') + '</article>';
	}).join('');
}
</script>"""
	inner = (
		LOCK_HTML.format(blurb="These posts are encrypted. The passphrase never "
		                       "leaves your browser.")
		+ '\n<div id="private-list"></div>\n'
		+ vault_script(salt, index_payload)
		+ "\n" + render_index
		+ f'\n<script>{PRIVATE_JS}</script>'
	)
	feed_page(head, foot, "private", "private.html", "cache — private", inner,
	          extra_head=noindex + "\n" + PRIVATE_STYLE)

	for post in posts:
		payload = seal(key, {k: post[k] for k in ("title", "iso", "date", "html")})
		page = PRIVATE_POST_TEMPLATE.format(
			noindex=noindex,
			favicon=FAVICON_TAG,
			theme=theme_link("../../"),
			style=PRIVATE_STYLE,
			tray=tray_html("private", post["slug"]),
			lock=LOCK_HTML.format(blurb="This post is encrypted."),
			vault=vault_script(salt, payload),
			script=PRIVATE_JS,
			backtotop=BACKTOTOP,
		)
		out_dir = os.path.join(OUT, "private", post["slug"])
		os.makedirs(out_dir, exist_ok=True)
		with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
			f.write(page)
	return len(posts)


# Built by hand rather than lifted from a mirrored page: a private post has no
# Write.as source, and nothing here may leak into the served HTML, so the title
# element, headings and body are all left empty for the JS to fill in.
PRIVATE_POST_TEMPLATE = """<!DOCTYPE HTML>
<html lang="en" dir="auto">
<head>
<meta charset="utf-8">
<title>private &mdash; cache</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{noindex}
{theme}
{favicon}
{style}
</head>
<body id="post">
{tray}
<article id="post-body" class="norm h-entry">
{lock}
<div id="private-post" hidden>
<h2 id="title" class="p-name dated"></h2>
<time class="dt-published" datetime=""></time>
<div class="e-content"></div>
</div>
</article>
{vault}
<script>
function renderVault(v){{
	document.title = v.title + ' \\u2014 cache';
	document.getElementById('title').textContent = v.title;
	var t = document.querySelector('#private-post time');
	if (v.date) {{ t.textContent = v.date; t.setAttribute('datetime', v.iso); }}
	else {{ t.remove(); }}
	// v.html is the author's own markup from _private/, decrypted client-side.
	document.querySelector('#private-post .e-content').innerHTML = v.html;
	document.getElementById('private-post').hidden = false;
}}
</script>
<script>{script}</script>
{backtotop}
</body>
</html>
"""


def main():
	# Populate the navigator's cache list before building any page that injects it.
	for slug in POSTS:
		title, _iso, _disp = extract_meta(slug)
		CACHE_ITEMS.append((slug, title))
	for slug in POSTS:
		build_post(slug)
	if REDIRECT_OLD_POST_URLS:
		build_redirects()
	build_reading_articles()
	retray_native_reading()
	build_index()
	# private.html reuses the feed template, so it is built from the same
	# head/foot as the public feeds — with the analytics tag stripped back out.
	sealed = build_private(*index_template())
	build_sitemap()
	build_robots()
	build_feed()  # after the reading pages: it reads their descriptions
	print(
		"Built:", len(POSTS), f"posts -> {POSTS_DIR_NOTE} +", len(READING),
		"reading articles",
		f"({len(EXTERNAL_STANDALONE)} external standalone links)",
		"+ 4 feed pages + sitemap.xml + feed.xml",
	)
	if sealed is None:
		print("  private feed: skipped (unchanged)")
	else:
		print(f"  private feed: {sealed} post(s) encrypted")


if __name__ == "__main__":
	main()
