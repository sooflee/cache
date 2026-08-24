#!/usr/bin/env python3
"""AES-256-GCM in pure Python, for the private-posts build step.

Vendored rather than pip-installed: this repo has no dependencies and no
virtualenv, the build machine has neither `cryptography` nor `pycryptodome`,
and LibreSSL's `openssl enc` refuses AEAD ciphers outright. All build.py needs
is one direction (encrypt), so that is all this implements.

The output format matches what SubtleCrypto's `decrypt('AES-GCM', ...)` expects
on the browser side: ciphertext with the 16-byte tag appended.

Correctness is pinned by selftest() at the bottom, which checks the FIPS-197
AES-256 block vector plus GCM test cases 13-14 from the Galois/Counter Mode
spec. Run this file directly to execute it.
"""

# ---------------------------------------------------------------- AES tables

def _xmul(a, b):
	"""Multiply two bytes in GF(2^8) with the AES polynomial. Used only to
	build the lookup tables below, never in the hot path."""
	r = 0
	for _ in range(8):
		if b & 1:
			r ^= a
		hi = a & 0x80
		a = (a << 1) & 0xFF
		if hi:
			a ^= 0x1B
		b >>= 1
	return r


def _build_sbox():
	inv = [0] * 256
	for i in range(1, 256):
		for j in range(1, 256):
			if _xmul(i, j) == 1:
				inv[i] = j
				break
	sbox = []
	for i in range(256):
		x = y = inv[i]
		for _ in range(4):
			x = ((x << 1) | (x >> 7)) & 0xFF
			y ^= x
		sbox.append(y ^ 0x63)
	return bytes(sbox)


SBOX = _build_sbox()
RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)

# T-tables: one lookup per state byte folds SubBytes, ShiftRows and MixColumns
# into a single 32-bit xor chain. Plain byte-at-a-time AES in Python is roughly
# an order of magnitude slower, which is the difference between a build that
# feels instant and one that stalls on every run.
_T0 = tuple(
	(_xmul(s, 2) << 24) | (s << 16) | (s << 8) | _xmul(s, 3) for s in SBOX
)
_rotr8 = lambda w: ((w >> 8) | (w << 24)) & 0xFFFFFFFF
_T1 = tuple(_rotr8(w) for w in _T0)
_T2 = tuple(_rotr8(w) for w in _T1)
_T3 = tuple(_rotr8(w) for w in _T2)


def _expand_key(key):
	"""AES-256 key schedule -> 15 round keys of four 32-bit words each."""
	if len(key) != 32:
		raise ValueError("expected a 256-bit key")
	nk, nr = 8, 14
	w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
	for i in range(nk, 4 * (nr + 1)):
		t = list(w[i - 1])
		if i % nk == 0:
			t = t[1:] + t[:1]
			t = [SBOX[b] for b in t]
			t[0] ^= RCON[i // nk - 1]
		elif i % nk == 4:
			t = [SBOX[b] for b in t]
		w.append([w[i - nk][j] ^ t[j] for j in range(4)])
	words = [(b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3] for b in w]
	return [words[4 * r:4 * r + 4] for r in range(nr + 1)], nr


def _encrypt_block(rk, nr, block):
	"""Encrypt one 16-byte block, state held as four column words."""
	s0 = int.from_bytes(block[0:4], "big") ^ rk[0][0]
	s1 = int.from_bytes(block[4:8], "big") ^ rk[0][1]
	s2 = int.from_bytes(block[8:12], "big") ^ rk[0][2]
	s3 = int.from_bytes(block[12:16], "big") ^ rk[0][3]
	for r in range(1, nr):
		k = rk[r]
		t0 = (_T0[s0 >> 24] ^ _T1[(s1 >> 16) & 0xFF]
		      ^ _T2[(s2 >> 8) & 0xFF] ^ _T3[s3 & 0xFF] ^ k[0])
		t1 = (_T0[s1 >> 24] ^ _T1[(s2 >> 16) & 0xFF]
		      ^ _T2[(s3 >> 8) & 0xFF] ^ _T3[s0 & 0xFF] ^ k[1])
		t2 = (_T0[s2 >> 24] ^ _T1[(s3 >> 16) & 0xFF]
		      ^ _T2[(s0 >> 8) & 0xFF] ^ _T3[s1 & 0xFF] ^ k[2])
		t3 = (_T0[s3 >> 24] ^ _T1[(s0 >> 16) & 0xFF]
		      ^ _T2[(s1 >> 8) & 0xFF] ^ _T3[s2 & 0xFF] ^ k[3])
		s0, s1, s2, s3 = t0, t1, t2, t3
	# Final round: SubBytes + ShiftRows, no MixColumns.
	k = rk[nr]
	out = bytearray(16)
	for i, (a, b, c, d) in enumerate((
		(s0, s1, s2, s3), (s1, s2, s3, s0), (s2, s3, s0, s1), (s3, s0, s1, s2),
	)):
		word = ((SBOX[a >> 24] << 24) | (SBOX[(b >> 16) & 0xFF] << 16)
		        | (SBOX[(c >> 8) & 0xFF] << 8) | SBOX[d & 0xFF]) ^ k[i]
		out[4 * i:4 * i + 4] = word.to_bytes(4, "big")
	return bytes(out)


# ------------------------------------------------------------------- GHASH

_R = 0xE1000000000000000000000000000000


def _gf_mul(x, y):
	"""Carry-less multiply in GF(2^128), GCM bit order. Table-building only."""
	z, v = 0, x
	for i in range(127, -1, -1):
		if (y >> i) & 1:
			z ^= v
		v = (v >> 1) ^ _R if v & 1 else v >> 1
	return z


def _ghash_table(h):
	"""Nibble-wise multiplication table for a fixed H: tab[j][n] = n·H shifted
	into nibble position j. Turns each GHASH block into 32 lookups instead of
	128 conditional shifts."""
	hi = int.from_bytes(h, "big")
	return [
		[0] + [_gf_mul(n << (4 * (31 - j)), hi) for n in range(1, 16)]
		for j in range(32)
	]


def _ghash(tab, data):
	y = 0
	for i in range(0, len(data), 16):
		chunk = data[i:i + 16]
		y ^= int.from_bytes(chunk + b"\0" * (16 - len(chunk)), "big")
		z = 0
		for j in range(32):
			n = (y >> (4 * (31 - j))) & 0xF
			if n:
				z ^= tab[j][n]
		y = z
	return y


def _pad16(b):
	return b + b"\0" * (-len(b) % 16)


# -------------------------------------------------------------------- API

def encrypt(key, nonce, plaintext, aad=b""):
	"""AES-256-GCM. Returns ciphertext || 16-byte tag.

	`nonce` must be 12 bytes: that is what WebCrypto's default is tuned for and
	the only length this implementation derives J0 for.
	"""
	if len(nonce) != 12:
		raise ValueError("expected a 96-bit nonce")
	rk, nr = _expand_key(key)
	tab = _ghash_table(_encrypt_block(rk, nr, b"\0" * 16))
	j0 = nonce + b"\x00\x00\x00\x01"

	ct = bytearray()
	counter = int.from_bytes(j0[12:], "big")
	for i in range(0, len(plaintext), 16):
		counter = (counter + 1) & 0xFFFFFFFF
		ks = _encrypt_block(rk, nr, nonce + counter.to_bytes(4, "big"))
		chunk = plaintext[i:i + 16]
		ct += bytes(a ^ b for a, b in zip(chunk, ks))

	s = _ghash(tab, _pad16(aad) + _pad16(bytes(ct))
	           + (len(aad) * 8).to_bytes(8, "big")
	           + (len(ct) * 8).to_bytes(8, "big"))
	mask = _encrypt_block(rk, nr, j0)
	tag = bytes(a ^ b for a, b in zip(s.to_bytes(16, "big"), mask))
	return bytes(ct) + tag


def selftest():
	# FIPS-197 C.3 — AES-256 single block.
	rk, nr = _expand_key(bytes(range(32)))
	got = _encrypt_block(rk, nr, bytes.fromhex("00112233445566778899aabbccddeeff"))
	assert got.hex() == "8ea2b7ca516745bfeafc49904b496089", got.hex()

	# GCM spec test case 13 — 256-bit key, empty plaintext and AAD.
	out = encrypt(b"\0" * 32, b"\0" * 12, b"")
	assert out.hex() == "530f8afbc74536b9a963b4f1c4cb738b", out.hex()

	# GCM spec test case 14 — one all-zero plaintext block.
	out = encrypt(b"\0" * 32, b"\0" * 12, b"\0" * 16)
	assert out.hex() == (
		"cea7403d4d606b6e074ec5d3baf39d18" "d0d1c8a799996bf0265b98b5d48ab919"
	), out.hex()

	# GCM spec test case 16 — non-trivial key, plaintext and AAD.
	key = bytes.fromhex(
		"feffe9928665731c6d6a8f9467308308feffe9928665731c6d6a8f9467308308")
	iv = bytes.fromhex("cafebabefacedbaddecaf888")
	pt = bytes.fromhex(
		"d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
		"1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39")
	aad = bytes.fromhex("feedfacedeadbeeffeedfacedeadbeefabaddad2")
	out = encrypt(key, iv, pt, aad)
	assert out.hex() == (
		"522dc1f099567d07f47f37a32a84427d643a8cdcbfe5c0c97598a2bd2555d1aa"
		"8cb08e48590dbb3da7b08b1056828838c5f61e6393ba7a0abcc9f662"
		"76fc6ece0f4e1768cddf8853bb2d551b"), out.hex()
	print("aesgcm selftest ok")


if __name__ == "__main__":
	selftest()
