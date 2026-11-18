/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Self-contained SHA-256 (FIPS 180-4) for checking the GPU firmware in the kernel without libkern's SHA256_* wrappers
 * (rbu5's gpu 5 got a different digest through them for a file whose bytes were right). Host test: tests/sha256_host.c. */
#ifndef RUAN_SHA256_H
#define RUAN_SHA256_H
#include <stddef.h>
#include <stdint.h>

static inline uint32_t ruan_sha256_ror(uint32_t x, unsigned n) {return (x >> n) | (x << (32 - n));}

static inline void ruan_sha256_block(uint32_t h[8], const uint8_t p[64])
{
	static const uint32_t k[64] = {
	    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01,
	    0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
	    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
	    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
	    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116, 0x1e376c08,
	    0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
	    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
	uint32_t w[64];
	for (unsigned i = 0; i < 16; i++)
		w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
	for (unsigned i = 16; i < 64; i++) {
		const uint32_t s0 = ruan_sha256_ror(w[i - 15], 7) ^ ruan_sha256_ror(w[i - 15], 18) ^ (w[i - 15] >> 3);
		const uint32_t s1 = ruan_sha256_ror(w[i - 2], 17) ^ ruan_sha256_ror(w[i - 2], 19) ^ (w[i - 2] >> 10);
		w[i] = w[i - 16] + s0 + w[i - 7] + s1;
	}
	uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
	for (unsigned i = 0; i < 64; i++) {
		const uint32_t t1 = hh + (ruan_sha256_ror(e, 6) ^ ruan_sha256_ror(e, 11) ^ ruan_sha256_ror(e, 25)) + ((e & f) ^ (~e & g)) + k[i] + w[i];
		const uint32_t t2 = (ruan_sha256_ror(a, 2) ^ ruan_sha256_ror(a, 13) ^ ruan_sha256_ror(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
		hh = g, g = f, f = e, e = d + t1, d = c, c = b, b = a, a = t1 + t2;
	}
	h[0] += a, h[1] += b, h[2] += c, h[3] += d, h[4] += e, h[5] += f, h[6] += g, h[7] += hh;
}

static inline void ruan_sha256(const void *data, size_t len, uint8_t out[32])
{
	uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
	const uint8_t *p = (const uint8_t *)data;
	size_t left = len;
	for (; left >= 64; left -= 64, p += 64) ruan_sha256_block(h, p);
	uint8_t tail[128] = {0};
	for (size_t i = 0; i < left; i++) tail[i] = p[i];
	tail[left] = 0x80;
	const size_t blocks = left < 56 ? 1 : 2;
	const uint64_t bits = (uint64_t)len * 8;
	for (unsigned i = 0; i < 8; i++) tail[blocks * 64 - 1 - i] = (uint8_t)(bits >> (8 * i));
	for (size_t b = 0; b < blocks; b++) ruan_sha256_block(h, tail + 64 * b);
	for (unsigned i = 0; i < 8; i++)
		out[4 * i] = (uint8_t)(h[i] >> 24), out[4 * i + 1] = (uint8_t)(h[i] >> 16), out[4 * i + 2] = (uint8_t)(h[i] >> 8), out[4 * i + 3] = (uint8_t)h[i];
}

/* 1 when data hashes to the 64-hex-digit digest `hex` (lower or upper case). The pinned digests stay hex strings copied from
 * sha256sum: a hand-typed byte array was wrong in rbu5 (byte 11 on). */
static inline int ruan_sha256_matches_hex(const void *data, size_t len, const char *hex)
{
	uint8_t d[32];
	ruan_sha256(data, len, d);
	for (unsigned i = 0; i < 64; i++) {
		const char c = hex[i];
		const unsigned v = c >= '0' && c <= '9' ? (unsigned)(c - '0') : c >= 'a' && c <= 'f' ? (unsigned)(c - 'a' + 10) :
		    c >= 'A' && c <= 'F' ? (unsigned)(c - 'A' + 10) : 16u;
		if (v > 15u || v != ((i & 1) ? (d[i / 2] & 15u) : (d[i / 2] >> 4))) return 0;
	}
	return hex[64] == '\0';
}
#endif
