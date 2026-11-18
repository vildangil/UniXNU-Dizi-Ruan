/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Stage-1 page tables for the GMU's context bank on the GPU SMMU (stream 5), stage S2b `gpu 6`. ARMv8 VMSA, 4 KiB granule,
 * 32-bit input (TCR.T0SZ 32: the walk starts at level 1, four L1 entries), on a bump-allocated pinned pool. Pages are Normal
 * non-cacheable (MAIR attr 0 = 0x44), RW at EL0/EL1 (AP 01), executable (the GMU runs its code from GMU VA 0x4000), AF set,
 * outer shareable. Pure C, no kernel calls: tests/gmu_mmu_host.c builds and walks the same layout on the host. */
#ifndef RUAN_GMU_MMU_H
#define RUAN_GMU_MMU_H
#include <stddef.h>
#include <stdint.h>

#define RUAN_PT_PAGE 4096u
#define RUAN_PT_VALID 1ull
#define RUAN_PT_TABLE 3ull                     /* level 1/2 table descriptor */
#define RUAN_PT_PAGE_DESC 3ull                 /* level 3 page descriptor */
#define RUAN_PT_ATTR_NC (0ull << 2)            /* AttrIndx 0 -> MAIR0 byte 0 = 0x44 (Normal NC) */
#define RUAN_PT_AP_RW_PRIV (0ull << 6)         /* AP[2:1] = 00: RW, EL1 privileged only (EL0 denied so GMU can fetch) */
#define RUAN_PT_AP_RW_USER (1ull << 6)         /* AP[2:1] = 01: RW, EL0 and EL1 */
#define RUAN_PT_AP_RO_PRIV (2ull << 6)         /* AP[2:1] = 10: RO, EL1 privileged only */
#define RUAN_PT_AP_RO_USER (3ull << 6)         /* AP[2:1] = 11: RO, EL0 and EL1 */
#define RUAN_PT_SH_OUTER (2ull << 8)
#define RUAN_PT_AF (1ull << 10)
#define RUAN_PT_PAGE_ATTRS (RUAN_PT_PAGE_DESC | RUAN_PT_ATTR_NC | RUAN_PT_AP_RW_PRIV | RUAN_PT_SH_OUTER | RUAN_PT_AF)
#define RUAN_PT_ATTRS_PRIV_RW RUAN_PT_PAGE_ATTRS /* 0x603 */
#define RUAN_PT_ATTRS_PRIV_RO (RUAN_PT_PAGE_DESC | RUAN_PT_ATTR_NC | RUAN_PT_AP_RO_PRIV | RUAN_PT_SH_OUTER | RUAN_PT_AF) /* 0x683 */
#define RUAN_PT_ATTRS_USER_RW (RUAN_PT_PAGE_DESC | RUAN_PT_ATTR_NC | RUAN_PT_AP_RW_USER | RUAN_PT_SH_OUTER | RUAN_PT_AF) /* 0x643 */
#define RUAN_PT_ATTRS_USER_RO (RUAN_PT_PAGE_DESC | RUAN_PT_ATTR_NC | RUAN_PT_AP_RO_USER | RUAN_PT_SH_OUTER | RUAN_PT_AF) /* 0x6c3 */
#define RUAN_PT_ADDR_MASK 0x0000fffffffff000ull
#define RUAN_SMMU_MAIR0 0x44u
#define RUAN_SMMU_TCR 0x00800020u              /* T0SZ 32, walks NC/non-shareable, TG0 4K, EPD1 (no TTBR1) */
#define RUAN_SMMU_TCR2 0x2u                    /* PASize 40 bits */

struct ruan_pt {
	uint8_t *cpu;           /* CPU view of the pool (page aligned) */
	uint64_t pa;            /* its physical address (page aligned) */
	uint32_t pages, used;   /* pool size and pages handed out; page 0 is the L1 table */
};

static inline uint64_t *ruan_pt_tbl(const struct ruan_pt *p, uint64_t pa) {return (uint64_t *)(p->cpu + (pa - p->pa));}

/* 0 when the pool is usable: page aligned, at least 2 pages, physical address below 2^40. Zeroes and reserves the L1 page. */
static inline int ruan_pt_init(struct ruan_pt *p, uint8_t *cpu, uint64_t pa, size_t bytes)
{
	if (!cpu || ((uintptr_t)cpu & (RUAN_PT_PAGE - 1)) || (pa & (RUAN_PT_PAGE - 1)) || bytes < 2 * RUAN_PT_PAGE ||
	    pa + bytes > (1ull << 40)) return -1;
	p->cpu = cpu, p->pa = pa, p->pages = (uint32_t)(bytes / RUAN_PT_PAGE), p->used = 1;
	for (size_t i = 0; i < RUAN_PT_PAGE; i++) cpu[i] = 0;
	return 0;
}

/* `pages` zeroed pages from the pool: their physical address, 0 when it is exhausted. */
static inline uint64_t ruan_pt_alloc(struct ruan_pt *p, uint32_t pages)
{
	if (!pages || pages > p->pages - p->used) return 0;
	const uint64_t pa = p->pa + (uint64_t)p->used * RUAN_PT_PAGE;
	for (size_t i = 0; i < (size_t)pages * RUAN_PT_PAGE; i++) p->cpu[(size_t)p->used * RUAN_PT_PAGE + i] = 0;
	p->used += pages;
	return pa;
}

/* The next-level table under entry `e` of table `t`, created when absent. 0 on exhaustion or a block entry in the way. */
static inline uint64_t ruan_pt_next(struct ruan_pt *p, uint64_t *t, unsigned e)
{
	if (!(t[e] & RUAN_PT_VALID)) {
		const uint64_t pa = ruan_pt_alloc(p, 1);
		if (!pa) return 0;
		t[e] = pa | RUAN_PT_TABLE;
	} else if ((t[e] & 3ull) != RUAN_PT_TABLE) return 0;
	return t[e] & RUAN_PT_ADDR_MASK;
}

/* Map [va, va+bytes) to [pa, ...) with specified attributes. */
static inline int ruan_pt_map_attr(struct ruan_pt *p, uint32_t va, uint64_t pa, uint32_t bytes, uint64_t attrs)
{
	if ((va | (uint32_t)pa) & (RUAN_PT_PAGE - 1) || !bytes || (uint64_t)va + bytes > (1ull << 32) || (pa & ~RUAN_PT_ADDR_MASK))
		return -1;
	for (uint64_t off = 0; off < bytes; off += RUAN_PT_PAGE) {
		const uint64_t v = (uint64_t)va + off;
		uint64_t *l1 = ruan_pt_tbl(p, p->pa);
		const uint64_t l2pa = ruan_pt_next(p, l1, (unsigned)((v >> 30) & 3));
		if (!l2pa) return -1;
		const uint64_t l3pa = ruan_pt_next(p, ruan_pt_tbl(p, l2pa), (unsigned)((v >> 21) & 511));
		if (!l3pa) return -1;
		uint64_t *l3 = ruan_pt_tbl(p, l3pa);
		const unsigned e = (unsigned)((v >> 12) & 511);
		if (l3[e] & RUAN_PT_VALID) return -1;
		l3[e] = ((pa + off) & RUAN_PT_ADDR_MASK) | attrs;
	}
	return 0;
}

/* Map or remap [va, va+bytes) to [pa, ...). Overwrites existing L3 page entries. */
static inline int ruan_pt_remap_attr(struct ruan_pt *p, uint32_t va, uint64_t pa, uint32_t bytes, uint64_t attrs)
{
	if ((va | (uint32_t)pa) & (RUAN_PT_PAGE - 1) || !bytes || (uint64_t)va + bytes > (1ull << 32) || (pa & ~RUAN_PT_ADDR_MASK))
		return -1;
	for (uint64_t off = 0; off < bytes; off += RUAN_PT_PAGE) {
		const uint64_t v = (uint64_t)va + off;
		uint64_t *l1 = ruan_pt_tbl(p, p->pa);
		const uint64_t l2pa = ruan_pt_next(p, l1, (unsigned)((v >> 30) & 3));
		if (!l2pa) return -1;
		const uint64_t l3pa = ruan_pt_next(p, ruan_pt_tbl(p, l2pa), (unsigned)((v >> 21) & 511));
		if (!l3pa) return -1;
		uint64_t *l3 = ruan_pt_tbl(p, l3pa);
		const unsigned e = (unsigned)((v >> 12) & 511);
		l3[e] = ((pa + off) & RUAN_PT_ADDR_MASK) | attrs;
	}
	return 0;
}

/* Map [va, va+bytes) to [pa, ...). Page-aligned va and pa, va+bytes within 4 GiB. Refuses (-1) an already-mapped page, so
 * two regions can never overlap; nothing is changed for pages before the one that failed only in the overlap case. */
static inline int ruan_pt_map(struct ruan_pt *p, uint32_t va, uint64_t pa, uint32_t bytes)
{
	return ruan_pt_map_attr(p, va, pa, bytes, RUAN_PT_PAGE_ATTRS);
}

/* Walk va as the SMMU would: the physical address, or ~0 when unmapped. */
static inline uint64_t ruan_pt_walk(const struct ruan_pt *p, uint32_t va)
{
	const uint64_t *l1 = ruan_pt_tbl(p, p->pa);
	const uint64_t d1 = l1[(va >> 30) & 3];
	if ((d1 & 3ull) != RUAN_PT_TABLE) return ~0ull;
	const uint64_t d2 = ruan_pt_tbl(p, d1 & RUAN_PT_ADDR_MASK)[(va >> 21) & 511];
	if ((d2 & 3ull) != RUAN_PT_TABLE) return ~0ull;
	const uint64_t d3 = ruan_pt_tbl(p, d2 & RUAN_PT_ADDR_MASK)[(va >> 12) & 511];
	if ((d3 & 3ull) != RUAN_PT_PAGE_DESC) return ~0ull;
	return (d3 & RUAN_PT_ADDR_MASK) | (va & (RUAN_PT_PAGE - 1));
}

/* The GMU regions gpu 6 maps: every firmware preallocation outside the TCMs (zero-size blocks of type 1 or 7: address and
 * byte count in `value`), then HFI and the log (KGSL gen7_hfi_init / gen7_gmu_memory_init, GMU_NONCACHED_KERNEL). */
#define RUAN_GMU_HFI_VA 0x60002000u
#define RUAN_GMU_HFI_BYTES 0x4000u            /* AdrenoHfi.c: exactly 16 KiB */
#define RUAN_GMU_LOG_VA 0x60006000u
#define RUAN_GMU_LOG_BYTES 0x4000u            /* kgsl_gmu_core.h GMU_LOG_SIZE */
#define RUAN_GMU_MAX_REGIONS 16u
struct ruan_gmu_region {uint32_t va, bytes; uint64_t pa;};
static inline int ruan_gmu_va_in_tcm(uint32_t va) {return va < 0x4000u || (va >= 0x10004000u && va < 0x10008000u);}

/* Collects the regions from the firmware (already size/hash checked), allocates and maps them. The count, or -1. */
static inline int ruan_gmu_layout(struct ruan_pt *p, const uint8_t *fw, size_t fw_bytes, struct ruan_gmu_region *r)
{
	unsigned n = 0;
	for (size_t o = 0; o + 16 <= fw_bytes;) {
		uint32_t h[4];
		for (unsigned i = 0; i < 16; i++) ((uint8_t *)h)[i] = fw[o + i];
		o += 16;
		if (h[1] > fw_bytes - o) return -1;
		if (!h[1] && (h[2] == 1u || h[2] == 7u) && h[3] && !ruan_gmu_va_in_tcm(h[0])) {
			if (n == RUAN_GMU_MAX_REGIONS - 2) return -1;
			if (h[0] & (RUAN_PT_PAGE - 1)) return -1;
			r[n].va = h[0], r[n].bytes = (h[3] + RUAN_PT_PAGE - 1) & ~(RUAN_PT_PAGE - 1), n++;
		}
		o += h[1];
	}
	r[n].va = RUAN_GMU_HFI_VA, r[n].bytes = RUAN_GMU_HFI_BYTES, n++;
	r[n].va = RUAN_GMU_LOG_VA, r[n].bytes = RUAN_GMU_LOG_BYTES, n++;
	for (unsigned i = 0; i < n; i++) {
		r[i].pa = ruan_pt_alloc(p, r[i].bytes / RUAN_PT_PAGE);
		if (!r[i].pa || ruan_pt_map(p, r[i].va, r[i].pa, r[i].bytes)) return -1;
	}
	return (int)n;
}

/* CPU pointer for GMU VA range [va, va+bytes) when it lies inside one region, else NULL. */
static inline uint8_t *ruan_gmu_cpu(const struct ruan_pt *p, const struct ruan_gmu_region *r, unsigned n, uint32_t va, uint32_t bytes)
{
	for (unsigned i = 0; i < n; i++)
		if (va >= r[i].va && (uint64_t)va + bytes <= (uint64_t)r[i].va + r[i].bytes) return p->cpu + (r[i].pa - p->pa) + (va - r[i].va);
	return NULL;
}
#endif
