/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* ruan Adreno 710 board facts for stages S2 (GMU boot to HFI ready) and S3 (SQE/CP + zap), gpu-dev/README.md.
 * Facts only, no code: the inputs a ruan prepare-sheng-gmu run (refs/UniXNU-Dizi-Ruan/scripts/prepare-sheng-gmu.py) and the
 * ShengGmu cold start (refs/sm7435-common/kits/Sm8550Platform/ShengGmu.c) need. Sources:
 *   dts = macOS/hardware/private/ruan-live.dts; gpucc/gcc = gcc-parrot.c / gpucc-parrot.c and KGSL = drivers/gpu/msm/ in
 *   OnePlusOSS/android_kernel_oneplus_sm8475 7278ce9a3c8539b4630d6988cc80f90c31c07336 (copies in gpu-dev/src-ref). */
#ifndef RUAN_GMU_BOARD_H
#define RUAN_GMU_BOARD_H
#include "RuanSha256.h"

/* Windows. qcom,gmu@3d69000 "qcom,gen7-gmu": reg gmu 0x3d68000+0x37000, gmu_pdc 0xb270000+0x10000, gmu_ao_blk_dec0
 * 0x3d40000+0x10000 (dts:16873-16876). qcom,kgsl-3d0: kgsl_3d0_reg_memory 0x3d00000+0x40000, cx_dbgc 0x3d61000+0x800,
 * rscc 0x3d50000+0x10000, cx_misc 0x3d9e000+0x1000 (dts:16136-16137). ShengGmu's window order: core, rscc, pdc, gpu, cx_misc.
 * NOTE: the GMU window 0x3d68000-0x3d9f000 overlaps GPUCC 0x3d90000-0x3d9a000 and CX_MISC: guard GMU writes by register. */
#define RUAN_GMU_BASE 0x03d68000ULL
#define RUAN_GMU_SIZE 0x37000ULL
#define RUAN_GMU_PDC_BASE 0x0b270000ULL
#define RUAN_GMU_PDC_SIZE 0x10000ULL
#define RUAN_GMU_AO_BASE 0x03d40000ULL
#define RUAN_GMU_RSCC_BASE 0x03d50000ULL
#define RUAN_GMU_RSCC_SIZE 0x10000ULL
#define RUAN_GPU_BASE 0x03d00000ULL
#define RUAN_GPU_SIZE 0x40000ULL
#define RUAN_GPU_CX_MISC_BASE 0x03d9e000ULL
#define RUAN_GPU_CX_MISC_SIZE 0x1000ULL

/* IRQs (GIC SPI): kgsl_3d0_irq 0x12c, freq_limiter 0x11e (dts:16138); GMU hfi 0x130, gmu 0x131 (dts:16877). */
#define RUAN_GPU_SPI 0x12cu
#define RUAN_GMU_HFI_SPI 0x130u
#define RUAN_GMU_SPI 0x131u

/* SMMU streams (kgsl-smmu@3da0000, qsmmu-v500): GPU user SID 0, secure SID 2, GMU SID 5 mask 0x400 (dts:16852-16889). */
#define RUAN_SMMU_SID_GPU 0x0u
#define RUAN_SMMU_SID_SECURE 0x2u
#define RUAN_SMMU_SID_GMU 0x5u
#define RUAN_SMMU_SID_GMU_MASK 0x400u

/* GMU clocks (dts:16880-16881, resolved with qcom,gpucc-parrot.h / qcom,gcc-parrot.h): gmu_clk GPU_CC_CX_GMU_CLK 0x913c,
 * cxo_clk GPU_CC_CXO_CLK 0x9144, axi_clk GCC_DDRSS_GPU_AXI_CLK 0x81154, memnoc_clk GCC_GPU_MEMNOC_GFX_CLK 0x81010,
 * ahb_clk GPU_CC_AHB_CLK 0x911c, hub_clk GPU_CC_HUB_CX_INT_CLK 0x9148, smmu_vote GPU_CC_HLOS1_VOTE_GPU_SMMU_CLK 0x7000.
 * GPUCC-relative except the two GCC ones (GCC-relative). */
#define RUAN_CC_CX_GMU_CLK 0x913c
#define RUAN_CC_CXO_CLK 0x9144
#define RUAN_CC_AHB_CLK 0x911c
#define RUAN_CC_HUB_CX_INT_CLK 0x9148
#define RUAN_CC_HUB_AON_CLK 0x93e8
#define RUAN_CC_SMMU_VOTE_CLK 0x7000
#define RUAN_GCC_DDRSS_GPU_AXI 0x81154
#define RUAN_GCC_GPU_MEMNOC_GFX 0x81010
#define RUAN_GCC_GPLL0_VOTE 0x62000      /* BIT(15) gcc_gpu_gpll0_clk_src, BIT(16) gcc_gpu_gpll0_div_clk_src */

/* Rates. The GMU node has no qcom,gmu-freq-table, so KGSL uses GMU_FREQ_MIN 200 MHz (kgsl_gmu_core.h:96, adreno_gen7_gmu.c
 * 1966-1971); gen7_3_0 sets no gmu_hub_clk_freq, so hub = 150 MHz (adreno_gen7.c:204). gpucc-parrot.c: gpu_cc_gmu_clk_src
 * (RCG 0x9318) F(200 MHz, GPLL0_OUT_MAIN_DIV sel 6, div 1.5); gpu_cc_hub_clk_src (RCG 0x93ec) F(150 MHz, GPLL0_OUT_MAIN_DIV
 * sel 6, div 2). Neither needs a GPU PLL; both need the GCC GPLL0 div vote (0x62000 BIT(16)). RCG CFG: SRC_SEL bits 8-10,
 * HID divider bits 0-4 = 2*div - 1. */
#define RUAN_CC_GMU_RCGR 0x9318
#define RUAN_CC_HUB_RCGR 0x93ec
#define RUAN_GMU_RCG_CFG ((6u << 8) | 2u)   /* 200 MHz */
#define RUAN_HUB_RCG_CFG ((6u << 8) | 3u)   /* 150 MHz */

/* GMU boot (KGSL adreno_gen7_gmu.c gen7_load_rsc_ucode 163-191, gen7_load_pdc_ucode 193-217, gen7_gmu_power_config
 * 219-227): the RSC sequence is generic gen7 (the same five SEQ_MEM words mainline uses for A7xx: eaaae5a0 e1a1ebab a2e0a581
 * ecac82e2 0020edad; PDC_SEQ_START 0x4520, MATCH 0x4510/0x4514), PDC GPU_SEQ_START 0 then ENABLE_PDC 0x80000001,
 * SYS_BUS/ICACHE/DCACHE_CONFIG 1. ShengGmu.c already does this for gen7; ruan changes the windows and the firmware only. */
#define RUAN_A710_CHIPID_GMU 0x07010000u   /* adreno.h ADRENO_GMU_CHIPID(0x07010000): core 7, major 1, minor 0, patch 0 */
#define RUAN_GMU_FW "gmu_gen70000.bin"     /* 57272 bytes, sha256 b2d3f0e2a98fd6259ab9ffef16df63265542e6cc9a970d53d476e823d432042a */
#define RUAN_GMU_FW_BYTES 57272u
#define RUAN_GMU_FW_SHA256 "b2d3f0e2a98fd6259ab9ffef16df63265542e6cc9a970d53d476e823d432042a"   /* sha256sum of the file */
/* The kernel's firmware check (RuanGpuPower.c gpu 5), shared with tests/sha256_host.c: size and pinned sha256sum hex. */
static inline int ruan_gmu_fw_ok(const uint8_t *data, size_t size)
{
	return data && size == RUAN_GMU_FW_BYTES && ruan_sha256_matches_hex(data, size, RUAN_GMU_FW_SHA256);
}

/* S3. SQE a710_sqe.fw (36308 bytes, c5588585...); zap a710_zap (mdt 4044 + b00 148 + b01 1948 + b02 3896; mbn 12088,
 * 21c5a569...), loaded by SCM PAS id 13 (amethyst AmethystSmc.c / GpuPowerProbe mode 15) into the DT's zap carveout
 * gpu_microcode_region 0x89e1a000+0x2000 (no-map, dts:164-167; kgsl-3d0 zap-shader memory-region). */
#define RUAN_SQE_FW "a710_sqe.fw"
#define RUAN_SQE_FW_BYTES 36308u
#define RUAN_ZAP_NAME "a710_zap"
#define RUAN_ZAP_PAS_ID 13u
#define RUAN_ZAP_REGION_BASE 0x89e1a000ULL
#define RUAN_ZAP_REGION_BYTES 0x2000ULL
/* The GPU pool: board.toml owned_memory_outside_reserved keeps it out of the memory-outside adoption (the tail of the HLOS
 * bank 0x880000000-0x8B9B00000); RuanGpuPower.c maps it write-combined after checking /chosen/darwinboot-memory-outside-kept. */
#define RUAN_GPU_POOL_BASE 0x8B8B00000ULL
#define RUAN_GPU_POOL_BYTES 0x1000000ULL
#define RUAN_GMU_POOL_BYTES 0x80000ULL     /* the GMU's slice at the start of the pool (65 of 128 pages used) */
#endif
