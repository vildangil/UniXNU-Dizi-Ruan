/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Adreno 710 / Gen7 GPU, CP, GMU and RBBM registers for Stage S3.
 * Values verified against Qualcomm KGSL (OnePlusOSS/android_kernel_oneplus_sm8475 gen7_reg.h). */
#ifndef RUAN_A710_REGS_H
#define RUAN_A710_REGS_H
#include <stdint.h>

/* GMU interrupt and status registers (dword offsets from GPU base) */
#define RUAN_GMU_PWR_CLK_STATUS             0x1f7e8u
#define RUAN_GMU_HFI_CTRL_STATUS            0x1f980u
#define RUAN_GMU_HFI_QTBL_INFO              0x1f984u
#define RUAN_GMU_HFI_QTBL_ADDR              0x1f985u
#define RUAN_GMU_HFI_CTRL_INIT              0x1f986u
#define RUAN_GMU_GMU2HOST_INTR_CLR          0x1f991u
#define RUAN_GMU_GMU2HOST_INTR_INFO         0x1f992u
#define RUAN_GMU_GMU2HOST_INTR_MASK         0x1f993u
#define RUAN_GMU_HOST2GMU_INTR_SET          0x1f994u

/* OOB GPU SET constants */
#define RUAN_OOB_GPU_SET_REQUEST            (1u << 30)
#define RUAN_OOB_GPU_SET_ACK                (1u << 31)
#define RUAN_GX_OFF_BITS                    0x3u  /* GX_HM_GDSC_POWER_OFF | GX_HM_CLK_OFF */

/* RBBM / GPU registers (dword offsets from GPU base 0x3d00000; byte = dword * 4) */
#define RUAN_RBBM_STATUS                    0x00210u
#define RUAN_RBBM_STATUS3                   0x00213u
#define RUAN_RBBM_INT_0_STATUS              0x00201u
#define RUAN_RBBM_INT_CLEAR_CMD             0x00037u   /* gen7_reg.h GEN7_RBBM_INT_CLEAR_CMD; KGSL writes the status back here */
#define RUAN_RBBM_INT_0_MASK                0x00038u   /* gen7_reg.h GEN7_RBBM_INT_0_MASK; interrupt mask */
#define RUAN_CP_INTERRUPT_STATUS            0x00823u   /* gen7_reg.h; detail for INT bit 9 HWERROR */
/* KGSL GEN7_INT_MASK enabling all RBBM interrupts (adreno_gen7.h) */
#define RUAN_A710_GEN7_INT_MASK             ((1u << 1) | (1u << 6) | (1u << 7) | (1u << 8) | (1u << 9) | (1u << 15) | \
                                             (1u << 17) | (1u << 20) | (1u << 22) | (1u << 23) | (1u << 24) | (1u << 25) | (1u << 28))
/* Error bits of RBBM_INT_0_STATUS (gen7_reg.h GEN7_INT_*, the error cases of KGSL adreno_gen7.c gen7_err_callback /
 * GEN7_INT_MASK): AHBERROR 1, ATBASYNCFIFOOVERFLOW 6, GPCERROR 7, HWERROR 9, ATBBUSOVERFLOW 22, HANGDETECT 23,
 * OUTOFBOUNDACCESS 24, UCHETRAP 25, TSBWRITEERROR 28. Bits 17/20 are RB_DONE_TS / CACHE_CLEAN_TS: normal completion. */
#define RUAN_A710_INT_HWERROR               (1u << 9)
#define RUAN_A710_INT_ERRORS                ((1u << 1) | (1u << 6) | (1u << 7) | (1u << 9) | (1u << 22) | (1u << 23) | \
                                             (1u << 24) | (1u << 25) | (1u << 28))
#define RUAN_RBBM_PERFCTR_CNTL              0x00500u
#define RUAN_RBBM_PERFCTR_GPU_BUSY_MASKED   0x0050bu
#define RUAN_RBBM_INTERFACE_HANG_INT_CNTL   0x0001fu
#define RUAN_RBBM_SECVID_TRUST_CNTL         0x0f400u
#define RUAN_RBBM_GBIF_HALT                 0x0000au
#define RUAN_GBIF_HALT                      0x03c45u

/* CP registers (dword offsets from GPU base) */
#define RUAN_CP_RB_BASE                     0x00800u
#define RUAN_CP_RB_BASE_HI                  0x00801u
#define RUAN_CP_RB_CNTL                     0x00802u
#define RUAN_CP_RB_RPTR_ADDR_LO             0x00804u
#define RUAN_CP_RB_RPTR_ADDR_HI             0x00805u
#define RUAN_CP_RB_RPTR                     0x00806u
#define RUAN_CP_RB_WPTR                     0x00807u
#define RUAN_CP_SQE_CNTL                    0x00808u
#define RUAN_CP_HW_FAULT                    0x00821u
#define RUAN_CP_INTERRUPT_STATUS            0x00823u
#define RUAN_CP_SQE_INSTR_BASE_LO           0x00830u
#define RUAN_CP_SQE_INSTR_BASE_HI           0x00831u
#define RUAN_CP_AHB_CNTL                    0x00840u
#define RUAN_CP_APRIV_CNTL                  0x00844u
#define RUAN_CP_PROTECT_CNTL                0x0084fu
#define RUAN_CP_BV_RB_RPTR_ADDR_LO          0x00a98u
#define RUAN_CP_BV_RB_RPTR_ADDR_HI          0x00a99u
#define RUAN_CP_BV_APRIV_CNTL               0x00ad0u

/* UCHE registers */
#define RUAN_UCHE_WRITE_THRU_BASE_LO        0x00e87u
#define RUAN_UCHE_WRITE_THRU_BASE_HI        0x00e88u
#define RUAN_UCHE_TRAP_BASE_LO              0x00e83u
#define RUAN_UCHE_TRAP_BASE_HI              0x00e84u
#define RUAN_UCHE_MODE_CNTL                 0x00e80u

/* Defaults */
#define RUAN_CP_RB_CNTL_DEFAULT             ((2u << 8) | 12u)  /* 32 KiB ring */
#define RUAN_BR_APRIV_DEFAULT               0x0000007fu        /* ICACHE, RBFETCH, RBPRIVLEVEL, RBRPWB, CDREAD, CDWRITE */
#define RUAN_BV_APRIV_DEFAULT               0x0000000fu        /* ICACHE, RBFETCH, RBPRIVLEVEL, RBRPWB */

#endif
