#!/usr/bin/env python3
"""A small Markdown -> HTML converter, for writing private posts in plaintext.

Vendored for the same reason as tools/aesgcm.py: this repo has no dependencies
and no virtualenv, and nothing Markdown-shaped is installed. It is not a
CommonMark implementation and doesn't try to be — it covers what a blog post
actually uses:

    headings (# and underlined)   lists, nested and ordered
    **bold** *italic* ~~strike~~  > blockquotes
    `code` and ``` fences         | pipe | tables |
    [links](url) and ![images]    --- rules, \\* escapes, <http://autolinks>

Raw HTML passes through, both inline and as a block, so anything this doesn't
handle can be written out longhand. Input is treated as trusted — it is the
author's own file — but stray `<`, `>` and `&` in prose are escaped so that
writing "a < b" or "AT&T" does the obvious thing.

Run this file directly to execute the self-test at the bottom.
"""
import re
import html

__all__ = ["convert"]

_BULLET = re.compile(r"^( *)([-*+])( +)(.*)$")
_ORDERED = re.compile(r"^( *)(\d{1,9})([.)])( +)(.*)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^ {0,3}(```|~~~)\s*([\w+#.-]*)\s*$")
_HR = re.compile(r"^ {0,3}([-*_])\s*(?:\1\s*){2,}$")
_QUOTE = re.compile(r"^ {0,3}>")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
_TABLE_DIV = re.compile(r"^ {0,3}\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
# An HTML block opens with a real tag. The trailing [\s/>] is what keeps an
# autolink like <https://x.dev> out of this — "https" is followed by a colon.
_HTML_BLOCK = re.compile(r"^ {0,3}<(?:[!/]|[A-Za-z][\w-]*(?:[\s/>]|$))")


def _marker(line):
	"""(kind, indent, content column, text, start number) for a list item."""
	m = _BULLET.match(line)
	if m:
		indent = len(m.group(1))
		return "ul", indent, indent + 1 + len(m.group(3)), m.group(4), None
	m = _ORDERED.match(line)
	if m:
		indent = len(m.group(1))
		col = indent + len(m.group(2)) + 1 + len(m.group(4))
		return "ol", indent, col, m.group(5), int(m.group(2))
	return None


def _starts_block(line):
	"""Does this line interrupt a paragraph?"""
	return bool(
		_HEADING.match(line) or _FENCE.match(line) or _HR.match(line)
		or _QUOTE.match(line) or _marker(line) or _HTML_BLOCK.match(line)
	)


# ------------------------------------------------------------------- inline

def _inline(text):
	"""Inline spans. Anything that must survive untouched — code, raw tags,
	finished links — is swapped out for a placeholder first and put back last,
	so later rules can't reach inside it."""
	kept = []

	def keep(s):
		kept.append(s)
		return f"\x00{len(kept) - 1}\x00"

	# Backslash escapes, before anything can act on the character escaped.
	text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!~>|])",
	              lambda m: keep(html.escape(m.group(1))), text)
	# Code spans: contents are literal, so escape and park them immediately.
	text = re.sub(r"(`+)(.+?)\1",
	              lambda m: keep("<code>" + html.escape(m.group(2).strip()) + "</code>"),
	              text, flags=re.S)
	# <http://…> autolinks, before the angle brackets get escaped.
	text = re.sub(r"<((?:https?|mailto):[^>\s]+)>",
	              lambda m: keep(f'<a href="{html.escape(m.group(1))}">{html.escape(m.group(1))}</a>'),
	              text)
	# Raw inline HTML and entities pass through verbatim.
	text = re.sub(r"</?[A-Za-z][\w-]*(?:\s[^<>]*)?/?>", lambda m: keep(m.group(0)), text)
	text = re.sub(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]{1,31});",
	              lambda m: keep(m.group(0)), text)
	# Whatever is left is prose, so a bare < or & is a literal one.
	text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

	def link(m, image=False):
		label, url, title = m.group(1), m.group(2), m.group(3)
		t = f' title="{title}"' if title else ""
		if image:
			return keep(f'<img src="{url}" alt="{label}"{t}>')
		return keep(f'<a href="{url}"{t}>{label}</a>')

	pattern = r"\[([^\]]*)\]\(\s*([^)\s]*)(?:\s+\"([^\"]*)\")?\s*\)"
	text = re.sub(r"!" + pattern, lambda m: link(m, image=True), text)
	text = re.sub(pattern, link, text)

	# The (?=\S) … (?<=\S) pair is what stops "a * b * c" from becoming emphasis:
	# the delimiters have to hug the text. Written as lookarounds rather than
	# consuming characters so that a single-character span like **b** still fits.
	# Strong before emphasis, or ** would be read as two nested *.
	text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", text, flags=re.S)
	text = re.sub(r"(?<![\w\\])__(?=\S)(.+?)(?<=\S)__(?!\w)", r"<strong>\1</strong>", text, flags=re.S)
	text = re.sub(r"\*(?=\S)([^*]+?)(?<=\S)\*", r"<em>\1</em>", text, flags=re.S)
	# Underscores only pair off outside words, so snake_case_names survive.
	text = re.sub(r"(?<![\w\\])_(?=\S)([^_]+?)(?<=\S)_(?!\w)", r"<em>\1</em>", text, flags=re.S)
	text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", text, flags=re.S)
	# Two trailing spaces is a hard line break.
	text = re.sub(r"  +\n", "<br>\n", text)

	# Put the parked spans back. Repeated because a link's label may itself hold
	# placeholders (code, emphasis) parked before the link was assembled.
	for _ in range(12):
		new = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
		if new == text:
			break
		text = new
	return text


# -------------------------------------------------------------------- blocks

def _table(lines, i):
	"""A GitHub-style pipe table, or None if this isn't one."""
	if i + 1 >= len(lines) or "|" not in lines[i] or not _TABLE_DIV.match(lines[i + 1]):
		return None

	def cells(line):
		line = line.strip()
		if line.startswith("|"):
			line = line[1:]
		if line.endswith("|"):
			line = line[:-1]
		return [c.strip() for c in line.split("|")]

	aligns = []
	for spec in cells(lines[i + 1]):
		left, right = spec.startswith(":"), spec.endswith(":")
		aligns.append("center" if left and right else
		              "right" if right else "left" if left else "")
	head = cells(lines[i])
	i += 2
	body = []
	while i < len(lines) and lines[i].strip() and "|" in lines[i]:
		body.append(cells(lines[i]))
		i += 1

	def row(values, tag):
		out = []
		for n, value in enumerate(values):
			style = f' style="text-align:{aligns[n]}"' if n < len(aligns) and aligns[n] else ""
			out.append(f"<{tag}{style}>{_inline(value)}</{tag}>")
		return "<tr>" + "".join(out) + "</tr>"

	rows = "\n".join(row(r, "td") for r in body)
	return (
		"<table>\n<thead>\n" + row(head, "th") + "\n</thead>\n"
		+ ("<tbody>\n" + rows + "\n</tbody>\n" if body else "")
		+ "</table>"
	), i


def _list(lines, i):
	kind, indent, content_col, _text, start = _marker(lines[i])
	entries, loose = [], False
	n = len(lines)
	while i < n:
		line = lines[i]
		if not line.strip():
			# A blank line stays inside the list only if the list continues
			# after it; otherwise it ends the list. Either way it makes the
			# list loose, which is what puts <p> inside each <li>.
			j = i
			while j < n and not lines[j].strip():
				j += 1
			mk = _marker(lines[j]) if j < n else None
			if j >= n or not ((mk and mk[1] == indent and mk[0] == kind)
			                  or lines[j].startswith(" " * (indent + 1))):
				break
			loose = True
			entries.append((False, ""))
			i = j
			continue
		mk = _marker(line)
		if mk and mk[1] < indent:
			break
		if mk and mk[1] == indent and mk[0] == kind:
			entries.append((True, line[mk[2]:]))
		elif line.startswith(" " * content_col):
			entries.append((False, line[content_col:]))
		elif mk or _HEADING.match(line) or _FENCE.match(line):
			break  # a different construct at this indent ends the list
		else:
			entries.append((False, line.strip()))  # lazy continuation
		i += 1

	items, current = [], None
	for is_new, text in entries:
		if is_new:
			current = [text]
			items.append(current)
		elif current is not None:
			current.append(text)

	rendered = []
	for item in items:
		inner = convert("\n".join(item))
		if not loose:
			# A tight item's text isn't wrapped in <p>, but anything after it
			# still is a block — so drop only the leading paragraph, which keeps
			# "- a\n  - b" as <li>a<ul>…</ul></li>.
			inner = re.sub(r"^<p>(.*?)</p>", r"\1", inner, count=1, flags=re.S)
		rendered.append(f"<li>{inner}</li>")
	attr = f' start="{start}"' if kind == "ol" and start not in (None, 1) else ""
	return f"<{kind}{attr}>\n" + "\n".join(rendered) + f"\n</{kind}>", i


def convert(md):
	"""Markdown -> an HTML fragment."""
	lines = md.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n")
	out, i, n = [], 0, len(lines)
	while i < n:
		line = lines[i]
		if not line.strip():
			i += 1
			continue

		m = _FENCE.match(line)
		if m:
			fence, lang = m.group(1), m.group(2)
			i += 1
			buf = []
			while i < n and lines[i].strip() != fence:
				buf.append(lines[i])
				i += 1
			i += 1
			cls = f' class="language-{lang}"' if lang else ""
			out.append(f"<pre><code{cls}>{html.escape(chr(10).join(buf))}</code></pre>")
			continue

		if _HR.match(line):
			out.append("<hr>")
			i += 1
			continue

		m = _HEADING.match(line)
		if m:
			level = len(m.group(1))
			out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
			i += 1
			continue

		if _QUOTE.match(line):
			buf = []
			while i < n and lines[i].strip() and not _HR.match(lines[i]):
				buf.append(re.sub(r"^ {0,3}> ?", "", lines[i]))
				i += 1
			out.append("<blockquote>\n" + convert("\n".join(buf)) + "\n</blockquote>")
			continue

		if _marker(line):
			block, i = _list(lines, i)
			out.append(block)
			continue

		table = _table(lines, i)
		if table:
			block, i = table
			out.append(block)
			continue

		if _HTML_BLOCK.match(line):
			buf = []
			while i < n and lines[i].strip():
				buf.append(lines[i])
				i += 1
			out.append("\n".join(buf))
			continue

		buf = []
		while i < n and lines[i].strip() and not _starts_block(lines[i]):
			# "===" under a paragraph underlines it; handled just past the loop.
			# ("---" gets here too, but as a horizontal rule via _starts_block.)
			if buf and _SETEXT.match(lines[i]):
				break
			if _table(lines, i):
				break
			# Strip indentation, but keep a trailing double space — that is the
			# hard-line-break marker, and _inline() looks for it.
			stripped = lines[i].strip()
			buf.append(stripped + "  " if stripped and lines[i].endswith("  ") else stripped)
			i += 1
		# An = or - rule directly under a paragraph underlines it into a heading.
		if buf and i < n and _SETEXT.match(lines[i]):
			level = 1 if lines[i].strip().startswith("=") else 2
			out.append(f"<h{level}>{_inline(' '.join(buf))}</h{level}>")
			i += 1
			continue
		if buf:
			out.append("<p>" + _inline("\n".join(buf)) + "</p>")
		else:  # a lone line that looked like a block start but matched nothing
			out.append("<p>" + _inline(line.strip()) + "</p>")
			i += 1
	return "\n".join(out)


def first_heading(md):
	"""(title, body-without-it) if the document opens with an H1, else (None, md).

	Lets a post take its title from its own first heading instead of repeating
	it in the front matter.
	"""
	lines = md.replace("\r\n", "\n").split("\n")
	k = 0
	while k < len(lines) and not lines[k].strip():
		k += 1
	if k >= len(lines):
		return None, md
	m = re.match(r"^ {0,3}#\s+(.*?)\s*#*\s*$", lines[k])
	if m:
		return m.group(1).strip(), "\n".join(lines[k + 1:])
	if k + 1 < len(lines) and re.match(r"^ {0,3}=+\s*$", lines[k + 1]) and lines[k].strip():
		return lines[k].strip(), "\n".join(lines[k + 2:])
	return None, md


def selftest():
	def check(md, want):
		got = convert(md)
		assert got == want, f"\n  input {md!r}\n  got   {got!r}\n  want  {want!r}"

	check("# Title", "<h1>Title</h1>")
	check("Title\n=====", "<h1>Title</h1>")
	check("Sub\n---", "<h2>Sub</h2>")
	check("plain text", "<p>plain text</p>")
	check("a **b** c *d* e", "<p>a <strong>b</strong> c <em>d</em> e</p>")
	check("~~gone~~", "<p><del>gone</del></p>")
	check("`a < b`", "<p><code>a &lt; b</code></p>")
	check("AT&T and a < b", "<p>AT&amp;T and a &lt; b</p>")
	check("&amp; stays", "<p>&amp; stays</p>")
	check(r"not \*emphasis\*", "<p>not *emphasis*</p>")
	check("snake_case_word stays", "<p>snake_case_word stays</p>")
	check("[t](u)", '<p><a href="u">t</a></p>')
	check('[t](u "ti")', '<p><a href="u" title="ti">t</a></p>')
	check("![a](i.png)", '<p><img src="i.png" alt="a"></p>')
	check("<https://x.dev>", '<p><a href="https://x.dev">https://x.dev</a></p>')
	check("a `code` [l](u)", '<p>a <code>code</code> <a href="u">l</a></p>')
	check("---", "<hr>")
	check("> quoted", "<blockquote>\n<p>quoted</p>\n</blockquote>")
	check("- a\n- b", "<ul>\n<li>a</li>\n<li>b</li>\n</ul>")
	check("1. a\n2. b", "<ol>\n<li>a</li>\n<li>b</li>\n</ol>")
	check("3. a", '<ol start="3">\n<li>a</li>\n</ol>')
	check("- a\n\n- b", "<ul>\n<li><p>a</p></li>\n<li><p>b</p></li>\n</ul>")
	check("- a\n  - b", "<ul>\n<li>a\n<ul>\n<li>b</li>\n</ul></li>\n</ul>")
	check("```py\nx = 1\n```", '<pre><code class="language-py">x = 1</code></pre>')
	check("```\na < b\n```", "<pre><code>a &lt; b</code></pre>")
	check("<div>raw</div>", "<div>raw</div>")
	check("text with <b>tag</b>", "<p>text with <b>tag</b></p>")
	check("| a | b |\n| --- | ---: |\n| 1 | 2 |",
	      '<table>\n<thead>\n<tr><th>a</th><th style="text-align:right">b</th></tr>\n</thead>\n'
	      '<tbody>\n<tr><td>1</td><td style="text-align:right">2</td></tr>\n</tbody>\n</table>')
	check("one\n\ntwo", "<p>one</p>\n<p>two</p>")
	check("line  \nbreak", "<p>line<br>\nbreak</p>")
	check("# H\n\npara\n\n- l", "<h1>H</h1>\n<p>para</p>\n<ul>\n<li>l</li>\n</ul>")

	assert first_heading("# T\n\nbody") == ("T", "\nbody")
	assert first_heading("no heading")[0] is None
	print("markdown selftest ok")


if __name__ == "__main__":
	selftest()
