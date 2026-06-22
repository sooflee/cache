# cache — archived

A static, self-contained archive of the blog formerly at **cache.bwang.io**
(previously hosted on [Write.as](https://write.as)). The blog is no longer
maintained; every post is preserved here read-only.

Each page carries a banner noting the blog is archived. The homepage
(`index.html`) lists all 12 posts in reverse-chronological order.

## Deploy

Pure static HTML — host the directory anywhere (Netlify, GitHub Pages, Cloudflare
Pages, S3, nginx). `index.html` is the entry point. No build step required to serve.
`sitemap.xml` and the per-page Open Graph / canonical URLs are anchored at
`BASE_URL` in `build.py` (default `https://cache.bwang.io`) — change it and rebuild
if you host the archive on a different domain.

Local preview:

```sh
python3 -m http.server
# open http://localhost:8000
```

## Layout

```
index.html             homepage — unified list of all posts (cache + reading)
<slug>.html            one cache post per file (12 total)
reading/<slug>/        mirrored reading articles (keep their own styling)
assets/css/inside.css  styling — adaptation of the Typora "Inside" theme
assets/fonts/inside/   Josefin Sans + Cascadia Code (self-hosted)
assets/img/            post images (localized from i.snap.as)
_mirror/               committed source snapshots (Write.as + GitHub Pages)
build.py               regenerates the pages from the mirrored sources in _mirror/
```

## Posts & navigation

The homepage has a **cache / reading / standalone toggle** (pure CSS, no JS) that
switches the list between the 12 cache posts (dated), the 9 reading articles, and
the standalone apps; it defaults to cache. Every article page carries a **left
tray**: a pull-tab on the left edge that slides open to the same three-way toggle
(defaulting to the feed of the article you're on) with the current post
highlighted.

## Reading articles

The reading articles were originally published on `www.bwang.io/<name>/`
(GitHub Pages). Each is mirrored under `reading/<slug>/`. A late-loading override
(`assets/css/reading-theme.css`) re-themes them toward the cache look: **Josefin
Sans on all of them**, plus the **narrow centered column** (flagged with
`<html class="cache-narrow">`) on **every reading article** for a consistent
format. They all share one header treatment (kicker · title · lead · meta · 2px
rule) and one **right-hand contents outline** (`nav.outline`; wine/real-estate's
sidebar TOC is re-tagged `class="toc outline"` so it moves to the right rail
while keeping its scroll-spy JS). ncaa's dark dashboard theme is re-skinned to the
light essay palette and given a matching header + outline (see the CACHE RE-SKIN
block appended to `reading/assets/ncaa/styles.css`).

The **standalone** tab holds the interactive apps, which can't be frozen into a
static archive (live backends, dynamic data), so they're **external links** to
their running versions rather than mirrored pages — defined in
`EXTERNAL_STANDALONE` in `build.py`, opened in a new tab with a `↗` cue:
Energy Trading Primer, Trading Signals, Stock Picker, Arbitrage Finder, Medical
RAG. No pages are built for them.

Two data-driven dashboards remain in the **reading** tab (poker-pros, ncaa) that
`fetch()` local JSON — they render over http(s) but not from a `file://`
double-click (browsers block `file://` fetch). real-estate's map pulls tiles from
the network.

## Styling

The site uses a local adaptation of the [Typora "Inside" theme](https://github.com/FishionYu/typora-inside-theme)
by FishionYu: a centered 600px column, Josefin Sans throughout, heavy headings
with margin labels (H1…H6), Cascadia Code for code, blue dotted links, and red
list markers. All fonts are self-hosted, so the site is fully self-contained.

## Notes

- A few images and two links point to `blog.bwang.io` (a defunct older blog).
  These were already broken on the live site and are preserved as-is.
- Post pages still include a small Write.as script that loads syntax
  highlighting from a CDN, but no post uses language-tagged code blocks, so it
  is a no-op; code renders with the local Cascadia Code styling.
