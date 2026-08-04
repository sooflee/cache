#!/usr/bin/env python3
"""Build a self-contained static archive of cache.bwang.io.

Reads the mirrored source pages from SRC, rewrites them to use local assets and
local .html links, injects an "no longer maintained" notice, and regenerates a
complete index listing every post. Idempotent: re-running rebuilds from SRC.
"""
import os
import re
import html
import urllib.parse

# Paths are resolved relative to this script so the build is portable and
# self-contained: the mirrored Write.as / GitHub-Pages sources live in _mirror/
# inside the repo (committed, not in ephemeral /tmp), and output goes to the repo
# root. Override with CACHE_SRC / CACHE_OUT env vars if needed.
ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("CACHE_SRC", os.path.join(ROOT, "_mirror"))
OUT = os.environ.get("CACHE_OUT", ROOT)

# Canonical address of the archived blog (used for og:url + sitemap.xml). Change
# this if the archive is deployed somewhere else.
BASE_URL = "https://cache.bwang.io"

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
	"""Write sitemap.xml listing every page, anchored at BASE_URL."""
	paths = (
		["index.html"]
		+ [f"{slug}.html" for slug in POSTS]
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
	("kimi-vs-claude", None, "Claude vs. Kimi K3: Should You Switch?"),
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
.nav-card #nav-standalone:checked ~ .nav-toggle label[for=nav-standalone]{
	color:#111;border-bottom-color:#357BB3;}
.nav-feed{display:none;}
.nav-card #nav-cache:checked ~ .nf-cache{display:block;}
.nav-card #nav-reading:checked ~ .nf-reading{display:block;}
.nav-card #nav-standalone:checked ~ .nf-standalone{display:block;}
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
}
@media (prefers-reduced-motion: reduce){
	.nav-card,.nav-restore{transition:none;}
}
</style>"""


def tray_html(context, active_slug=None):
	"""Left-drawer tray listing the home link + every post (cache + reading).

	`context` sets the relative link prefixes: "root" for top-level pages,
	"reading" for the mirrored articles under reading/<slug>/.
	"""
	standalone_slugs = {slug for slug, _cn, _label in STANDALONE}
	if context == "reading":
		home = "../../index.html"
		read_href = "../{}/index.html".format
		cache_href = "../../{}.html".format
		local_href = "../../{}".format
		# Default the toggle to the feed that holds the current article.
		if active_slug in standalone_slugs:
			cache_checked, reading_checked, standalone_checked = "", "", " checked"
		else:
			cache_checked, reading_checked, standalone_checked = "", " checked", ""
		# These pages don't load inside.css, so ship Josefin Sans + entrance anim.
		face = READING_EXTRA.format(p="../../assets")
	else:
		home = "index.html"
		read_href = "reading/{}/index.html".format
		cache_href = "{}.html".format
		local_href = "{}".format
		cache_checked, reading_checked, standalone_checked = " checked", "", ""
		face = ""

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
		+ f'<input type="radio" name="nav-feed" id="nav-cache" class="nav-radio"{cache_checked}>'
		+ f'<input type="radio" name="nav-feed" id="nav-reading" class="nav-radio"{reading_checked}>'
		+ f'<input type="radio" name="nav-feed" id="nav-standalone" class="nav-radio"{standalone_checked}>'
		+ '<div class="nav-toggle"><label for="nav-cache">cache</label>'
		+ '<label for="nav-reading">reading</label>'
		+ '<label for="nav-standalone">standalone</label></div>'
		+ f'<div class="nav-feed nf-cache">{cache_items}</div>'
		+ f'<div class="nav-feed nf-reading">{reading_items}</div>'
		+ f'<div class="nav-feed nf-standalone">{standalone_items}</div>'
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
THEME_LINK = '<link rel="stylesheet" type="text/css" href="assets/css/inside.css" />'

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


def rewrite_common(text):
	"""Asset + link rewrites shared by every page."""
	# Replace the Write.as theme stylesheet with our local Inside theme.
	text = text.replace(
		'<link rel="stylesheet" type="text/css" '
		'href="https://cdn.writeas.net/css/write.7a8d594726b6871de2afc.css" />',
		THEME_LINK,
	)
	# Local snap.as images
	text = re.sub(r"https://i\.snap\.as/([A-Za-z0-9]+\.png)", r"assets/img/\1", text)
	# Drop the RSS alternate <link> (no feed on the archive)
	text = re.sub(r'\s*<link rel="alternate"[^>]*?/>\n?', "\n", text)
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
			f'style="background-image:url(\'assets/img/yt/{m.group(1)}.jpg\')">'
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
	for slug in POSTS:
		text = text.replace(f"https://cache.bwang.io/{slug}", f"{slug}.html")
	# Any leftover feed link -> homepage
	text = text.replace("https://cache.bwang.io/feed/", "index.html")
	# Root / blog-title links -> index.html
	text = re.sub(r'href="https?://cache\.bwang\.io/"', 'href="index.html"', text)
	text = re.sub(r'href="https?://cache\.bwang\.io"', 'href="index.html"', text)
	# blog-title and author links use href="/"
	text = text.replace('href="/" class="h-card', 'href="index.html" class="h-card')
	text = text.replace('rel="author" href="/"', 'rel="author" href="index.html"')
	# One shared favicon on every page (cache posts + homepage).
	text = set_favicon(text)
	# Analytics on every page.
	text = inject_ga(text)
	return text


def build_post(slug):
	with open(os.path.join(SRC, f"{slug}.html"), encoding="utf-8") as f:
		text = f.read()
	text = rewrite_common(text)
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
	text = inject_tray(text, "root", slug)
	text = inject_backtotop(text)
	with open(os.path.join(OUT, f"{slug}.html"), "w", encoding="utf-8") as f:
		f.write(text)


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
	IS the source. Swapping just the <div class="nav-float"> block keeps their
	hand-written markup intact while still picking up list reordering and new
	entries. The surrounding <style> blocks are order-independent, so they are
	left alone."""
	for slug, _cn, _label in NATIVE_READING:
		path = os.path.join(OUT, "reading", slug, "index.html")
		if not os.path.isfile(path):
			print(f"  warning: {path} missing, skipping tray refresh")
			continue
		with open(path, encoding="utf-8") as f:
			text = f.read()
		tray = re.search(
			r'<div class="nav-float">.*?<div class="nav-feed nf-standalone">.*?</div></div></div>',
			text, flags=re.S,
		)
		if not tray:
			print(f"  warning: no tray found in {path}, skipping")
			continue
		fresh = re.search(
			r'<div class="nav-float">.*',
			tray_html("reading", slug), flags=re.S,
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


def build_index():
	# Reuse the real homepage as a template so header/footer/styles match exactly.
	with open(os.path.join(SRC, "index.html"), encoding="utf-8") as f:
		tpl = f.read()
	tpl = rewrite_common(tpl)

	head = tpl[: tpl.index("<section")]
	# Footer: from the real footer tag onward. The homepage lists posts but shows
	# no video, so drop the lite-YouTube script that rewrite_common injected.
	foot = tpl[tpl.index("<footer") :]
	foot = re.sub(r'\t*<script id="yt-lite-script">.*?</script>\n?', "", foot, flags=re.S)

	# Cache posts (dated, reverse-chronological).
	cache_rows = []
	for slug in POSTS:
		title, iso, disp = extract_meta(slug)
		cache_rows.append(
			'<article class="norm h-entry">\n'
			f'\t<h2 class="post-title"><a href="{slug}.html">{html.escape(title)}</a></h2>\n'
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

	# Pure-CSS toggle: the radios + labels + feeds are all siblings of #wrapper
	# so :checked ~ rules can show one feed at a time (no JavaScript). Default: cache.
	toggle = (
		'<input type="radio" name="feed" id="feed-cache" class="feed-radio" checked>\n'
		'<input type="radio" name="feed" id="feed-reading" class="feed-radio">\n'
		'<input type="radio" name="feed" id="feed-standalone" class="feed-radio">\n'
		'<div class="feed-toggle">'
		'<label for="feed-cache">cache</label>'
		'<label for="feed-reading">reading</label>'
		'<label for="feed-standalone">standalone</label>'
		'</div>\n'
	)
	body = (
		'<section id="wrapper">\n\n'
		+ toggle
		+ '<div class="feed feed-cache">\n' + "\n".join(cache_rows) + '\n</div>\n'
		+ '<div class="feed feed-reading">\n' + "\n".join(reading_rows) + '\n</div>\n'
		+ '<div class="feed feed-standalone">\n' + "\n".join(standalone_rows) + '\n</div>\n'
		+ '\n\t\t</section>\n\n\t\t'
	)
	out = head + body + foot
	with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
		f.write(out)


def main():
	# Populate the navigator's cache list before building any page that injects it.
	for slug in POSTS:
		title, _iso, _disp = extract_meta(slug)
		CACHE_ITEMS.append((slug, title))
	for slug in POSTS:
		build_post(slug)
	build_reading_articles()
	retray_native_reading()
	build_index()
	build_sitemap()
	print(
		"Built:", len(POSTS), "posts + index +", len(READING), "reading articles",
		f"({len(EXTERNAL_STANDALONE)} external standalone links) + sitemap.xml",
	)


if __name__ == "__main__":
	main()
