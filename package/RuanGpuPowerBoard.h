// SPDX-License-Identifier: BSD-2-Clause-Patent
// ruan (SM7435 "parrot", Adreno 710) GPU power observation and CX power-up: stage S1 of gpu-dev/README.md.
// The gated logic (gpb_io, gpb_result, gpb_rd, gpb_run) is copied unchanged from refs/UniXNU-amethyst/scripts/log/GpuPowerBoard.h
// (itself rootstockos/UniXNU-asteroids e12eb61a, BSD-2-Clause-Patent), lines 139-179 and 195-318. Only the board constants
// below are ruan's, each with its source. Modes: 1 reads only; 2 adds the one write Linux's GCC probe makes
// (gcc_gpu_cfg_ahb_clk enable); 3 powers the CX GDSC as the downstream gdsc-regulator does and turns on gpu_cc_ahb_clk and
// gpu_cc_hlos1_vote_gpu_smmu_clk, then reads the GPU SMMU's global space 0. Nothing here touches hardware itself.
#ifndef RUAN_GPU_POWER_BOARD_H
#define RUAN_GPU_POWER_BOARD_H
#include <stdint.h>

#define GPB_MAX_MODE 16u

// Live DT (macOS/hardware/private/ruan-live.dts): clock-controller@100000 "qcom,parrot-gcc" reg 0x100000+0x1f4200 (6623-6624),
// clock-controller@3d90000 "qcom,parrot-gpucc" reg 0x3d90000+0xa000 (6663-6665), kgsl-smmu 0x3da0000 (16891-16905),
// kgsl-3d0 0x3d00000+0x40000 (16136).
#define GPB_GCC_BASE 0x00100000ULL
#define GPB_GCC_GPU_PAGE 0x00181000ULL    // GCC + 0x81000: the GPU branches (gcc-parrot.c GCC_GPU_BCR 0x81000)
#define GPB_GCC_VOTE_PAGE 0x00162000ULL   // GCC + 0x62000: gcc_gpu_gpll0{,_div}_clk_src enable_reg
#define GPB_GPUCC_BASE 0x03d90000ULL
#define GPB_GPUCC_SIZE 0xa000ULL
#define GPB_SMMU_BASE 0x03da0000ULL
#define GPB_SMMU_GR0_SIZE 0x1000ULL
#define GPB_GPU_BASE 0x03d00000ULL
#define GPB_GPU_WINDOW 0x1000ULL

// gcc-parrot.c (OnePlusOSS/android_kernel_oneplus_sm8475 7278ce9a, drivers/clk/qcom/gcc-parrot.c): the probe keeps
// gcc_gpu_cfg_ahb_clk on with regmap_update_bits(regmap, 0x81004, BIT(0), BIT(0)) (line 2987). Branches:
// gcc_gpu_memnoc_gfx_clk 0x81010 (BRANCH_HALT_VOTED, line 1606), gcc_gpu_snoc_dvm_gfx_clk 0x81018 (BRANCH_HALT_DELAY, 1622),
// gcc_ddrss_gpu_axi_clk 0x81154 (BRANCH_HALT_SKIP, 1460), gcc_gpu_gpll0_clk_src 0x62000 BIT(15) (1572),
// gcc_gpu_gpll0_div_clk_src 0x62000 BIT(16) (1589). Offsets relative to the mapped page.
#define GPB_GCC_GPU_CFG_AHB 0x004
#define GPB_GCC_GPU_MEMNOC_GFX 0x010
#define GPB_GCC_GPU_SNOC_DVM_GFX 0x018
#define GPB_GCC_DDRSS_GPU_AXI 0x154
#define GPB_GCC_PLL_VOTE 0x000
#define GPB_GCC_GPLL0_GPU (1u << 15)
#define GPB_GCC_GPLL0_DIV_GPU (1u << 16)
#define GPB_CBCR_CLK_OFF (1u << 31)
#define GPB_CBCR_ENABLE (1u << 0)

// GDSCs, live DT: qcom,gdsc@3d99108 gpu_cc_cx_gdsc reg 0x3d99108, hw-ctrl-addr -> syscon@3d9953c, qcom,clk-dis-wait-val 8,
// qcom,retain-regs (dts:12200-12218); qcom,gdsc@3d9905c gpu_cc_gx_gdsc (dts:12245-12252). gpucc-parrot.c (same commit):
// gpu_cc_ahb_clk 0x911c (BRANCH_HALT_DELAY, line 341), gpu_cc_cx_gmu_clk 0x913c (395), gpu_cc_hlos1_vote_gpu_smmu_clk 0x7000
// (BRANCH_HALT_VOTED, 502). Offsets relative to GPUCC_BASE.
#define GPB_CC_CX_GDSCR 0x9108
#define GPB_CC_CX_GDS_HW_CTRL 0x953c
#define GPB_CC_GX_GDSCR 0x905c
#define GPB_CC_AHB_CLK 0x911c
#define GPB_CC_CX_GMU_CLK 0x913c
#define GPB_CC_SMMU_VOTE_CLK 0x7000
#define GPB_CC_HUB_CX_INT_CLK 0x9148     // gpucc-parrot.c gpu_cc_hub_cx_int_clk (BRANCH_HALT, line 533)
#define GPB_GDSC_PWR_ON (1u << 31)
#define GPB_GDSC_SW_COLLAPSE (1u << 0)
// Downstream gdsc-regulator.c (qcom,gdsc), as amethyst used it: HW_CONTROL BIT(1), SW_OVERRIDE BIT(2), RETAIN_FF BIT(11),
// CLK_DIS_WAIT 0xF << 12 set to the node's 8; poll PWR_ON in the hw-ctrl register 1500 x 1 us.
#define GPB_GDSC_HW_CONTROL (1u << 1)
#define GPB_GDSC_SW_OVERRIDE (1u << 2)
#define GPB_GDSC_RETAIN_FF (1u << 11)
#define GPB_GDSC_CLK_DIS_WAIT_MASK (0xFu << 12)
#define GPB_GDSC_CLK_DIS_WAIT_VAL (8u << 12)
#define GPB_GDSC_POLL_TRIES 1500u
#define GPB_BRANCH_HALT_DELAY_US 10u
#define GPB_VOTE_POLL_US 500u

// ARM SMMUv2 global space 0 (IHI 0062D.c): sCR0 0x0, ID0 0x20, ID1 0x24, ID2 0x28, sGFSR 0x48; SMRn 0x800 + 4n, S2CRn 0xc00 + 4n.
#define GPB_SMMU_SCR0 0x0
#define GPB_SMMU_ID0 0x20
#define GPB_SMMU_ID1 0x24
#define GPB_SMMU_ID2 0x28
#define GPB_SMMU_GFSR 0x48
#define GPB_SMMU_SMR(n) (0x800 + 4 * (n))
#define GPB_SMMU_S2CR(n) (0xc00 + 4 * (n))
#define GPB_SMMU_SMR_VALID (1u << 31)
#define GPB_SMMU_MAX_SMR 32u

// gen7: RBBM_STATUS is dword 0x210 (KGSL gen7_reg.h GEN7_RBBM_STATUS); read only once GX is on, which needs the GMU (S2).
#define GPB_RBBM_STATUS_BYTES (0x210 * 4)

// ruan change to amethyst's stage 3 gate (rb18g1 2026-11-14, gpu-dev/README.md): ruan's kgsl-smmu@3da0000 lists six clocks
// (dts:16907-16908: gpu_cc_cx_gmu, gpu_cc_hub_cx_int, gpu_cc_hlos1_vote_gpu_smmu, gcc_gpu_memnoc_gfx, gcc_gpu_snoc_dvm_gfx,
// gpu_cc_ahb) where volcano's listed four. g1 read cx_gmu 0x80000221 and snoc_dvm 0x80000001 (CLK_OFF). The SMMU's global
// space is read only when cx_gmu, hub_cx_int and snoc_dvm read running after the CX power-up (memnoc is hw-gated, voted and
// reads off when idle, so it is not part of the gate). Otherwise smmu = skip and smmu_why names the first clock that was off;
// bringing cx_gmu/hub up (their RCGs) belongs to stage S2.

enum gpb_state {GPB_NOT_RUN = 0, GPB_DONE = 1, GPB_SKIPPED_PREREQ = 2, GPB_SKIPPED_MODE = 3, GPB_NOMAP = 4};
static inline const char *gpb_state_text(enum gpb_state s) {
    switch (s) {case GPB_DONE: return "ok"; case GPB_SKIPPED_PREREQ: return "skip"; case GPB_SKIPPED_MODE: return "off";
                case GPB_NOMAP: return "nomap"; default: return "-";}
}

struct gpb_io {
    void *cookie;
    int (*read32)(void *cookie, unsigned window, uint32_t offset, uint32_t *out);   // 0 on success
    int (*write32)(void *cookie, unsigned window, uint32_t offset, uint32_t value);
    // Optional: called before each block is first touched (GPB_WIN_*), so a probe can log where it is before a read that could
    // hang the bus. NULL in tests that do not need it.
    void (*stage)(void *cookie, unsigned window);
    void (*delay_us)(void *cookie, unsigned us);   // mode 3 only; may be NULL where no mode 3 runs
};
#define GPB_STAGE_CX_GDSC 0x20u   // io->stage marker for the CX power-up, apart from every window index
enum {GPB_WIN_GCC_GPU = 0, GPB_WIN_GCC_VOTE = 1, GPB_WIN_GPUCC = 2, GPB_WIN_SMMU = 3, GPB_WIN_GPU = 4, GPB_WINDOWS = 5};

struct gpb_result {
    unsigned mode;                       // 1 read-only; 2 additionally enable gcc_gpu_cfg_ahb_clk if it is off (as Linux does)
    enum gpb_state gcc, cc, smmu, gpu;
    uint32_t cfg_ahb, cfg_ahb_after, memnoc, dvm, axi, pll_vote;
    uint32_t cx_gdscr, cx_hwctrl, gx_gdscr, cc_ahb, cc_smmu, cc_gmu;
    uint32_t scr0, id0, id1, id2, gfsr;
    unsigned num_smr, smr_valid;         // the stream-match survey (stage 3): entries read, entries with VALID set
    uint32_t smr[GPB_SMMU_MAX_SMR], s2cr[GPB_SMMU_MAX_SMR];
    uint32_t rbbm_status;
    uint32_t gate_gmu, gate_hub, gate_dvm;   // ruan: the three extra SMMU clocks, read after the CX power-up
    unsigned smmu_why;                       // ruan: 0 ok/not tried, 1 cx_gmu off, 2 hub_cx_int off, 3 snoc_dvm off
    // Mode 3: the CX GDSCR before, after the probe-init write and after enabling; the hw-ctrl status it polled and the tries it
    // took; the two clocks before. powered_cx and powered_clocks are 1 only when the status read confirmed them.
    uint32_t cx_before, cx_init, cx_after, cx_hwctrl_after, cc_ahb_before, cc_smmu_before;
    unsigned cx_tries, powered_cx, powered_clocks, cx_refused;
    unsigned enabled_ahb;                // 1 if mode 2 wrote the enable bit
    unsigned writes;                     // every write attempted (mode 1: always 0)
    int io_error;
};

static inline int gpb_clock_on(uint32_t cbcr) {return (cbcr & GPB_CBCR_CLK_OFF) == 0;}
// gcc_gpu_cfg_ahb_clk: the enable bit is the test (an idle branch with hardware clock gating can read CLK_OFF while enabled).
static inline int gpb_cfg_ahb_enabled(uint32_t cbcr) {return (cbcr & GPB_CBCR_ENABLE) != 0;}
static inline int gpb_gdsc_on(uint32_t gdscr) {return (gdscr & GPB_GDSC_PWR_ON) != 0;}

static inline int gpb_rd(const struct gpb_io *io, struct gpb_result *r, unsigned window, uint32_t offset, uint32_t *out) {
    uint32_t v = 0;
    if (io->read32(io->cookie, window, offset, &v)) {r->io_error = 1; *out = 0; return -1;}
    *out = v;
    return 0;
}

// The gated sequence. `have` is a bitmask of mapped windows (1 << GPB_WIN_*); a missing window makes its stage GPB_NOMAP.
// A mode above GPB_MAX_MODE runs nothing.
static inline void gpb_run(const struct gpb_io *io, unsigned mode, unsigned have, struct gpb_result *r) {
    __builtin_memset(r, 0, sizeof *r);
    r->mode = mode;
    if (!mode || mode > GPB_MAX_MODE) {r->gcc = r->cc = r->smmu = r->gpu = GPB_SKIPPED_MODE; return;}
    if (!(have & (1u << GPB_WIN_GCC_GPU))) {r->gcc = r->cc = r->smmu = r->gpu = GPB_NOMAP; return;}
    // Stage 1: GCC, always clocked (the same block family the UFS bring-up reads).
    if (io->stage) io->stage(io->cookie, GPB_WIN_GCC_GPU);
    if (gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_CFG_AHB, &r->cfg_ahb)) {r->cc = r->smmu = r->gpu = GPB_SKIPPED_PREREQ; return;}
    gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_MEMNOC_GFX, &r->memnoc);
    gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_SNOC_DVM_GFX, &r->dvm);
    gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_DDRSS_GPU_AXI, &r->axi);
    if (have & (1u << GPB_WIN_GCC_VOTE)) gpb_rd(io, r, GPB_WIN_GCC_VOTE, GPB_GCC_PLL_VOTE, &r->pll_vote);
    r->cfg_ahb_after = r->cfg_ahb;
    if (!gpb_cfg_ahb_enabled(r->cfg_ahb) && mode >= 2) {
        // The single write gcc-volcano's probe makes; mode 1 never writes.
        ++r->writes;
        if (!io->write32(io->cookie, GPB_WIN_GCC_GPU, GPB_GCC_GPU_CFG_AHB, r->cfg_ahb | GPB_CBCR_ENABLE)) {
            r->enabled_ahb = 1;
            gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_CFG_AHB, &r->cfg_ahb_after);
        } else r->io_error = 1;
    }
    r->gcc = GPB_DONE;
    // Stage 2: GPUCC registers need gcc_gpu_cfg_ahb_clk.
    if (!(have & (1u << GPB_WIN_GPUCC))) r->cc = GPB_NOMAP;
    else if (!gpb_cfg_ahb_enabled(r->cfg_ahb_after)) r->cc = GPB_SKIPPED_PREREQ;
    else {
        if (io->stage) io->stage(io->cookie, GPB_WIN_GPUCC);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, &r->cx_gdscr);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GDS_HW_CTRL, &r->cx_hwctrl);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_GX_GDSCR, &r->gx_gdscr);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_AHB_CLK, &r->cc_ahb);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_SMMU_VOTE_CLK, &r->cc_smmu);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GMU_CLK, &r->cc_gmu);
        r->cc = GPB_DONE;
    }
    // Mode 3: power CX (downstream gdsc-regulator.c) when stage 2 read it collapsed, then the SMMU's two GPU-CC clocks.
    r->cx_before = r->cx_gdscr; r->cc_ahb_before = r->cc_ahb; r->cc_smmu_before = r->cc_smmu;
    if (mode >= 3 && r->cc == GPB_DONE && !gpb_gdsc_on(r->cx_gdscr) && !gpb_gdsc_on(r->cx_hwctrl)) {
        int bad = 0;
        uint32_t v = r->cx_gdscr;
        if (io->stage) io->stage(io->cookie, GPB_STAGE_CX_GDSC);   // announce the CX power-up before its first write
        if (v & GPB_GDSC_HW_CONTROL) r->cx_refused = 1;   // gdsc_enable: "Invalid enable while ... under HW control"
        else {
            // Probe-time init: HW trigger and SW override off, the wait between states from qcom,clk-dis-wait-val.
            v = (v & ~(GPB_GDSC_HW_CONTROL | GPB_GDSC_SW_OVERRIDE | GPB_GDSC_CLK_DIS_WAIT_MASK)) | GPB_GDSC_CLK_DIS_WAIT_VAL;
            ++r->writes; bad |= io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, v);
            bad |= gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, &r->cx_init);
            if (!bad) {
                v = r->cx_init & ~GPB_GDSC_SW_COLLAPSE;   // enable
                ++r->writes; bad |= io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, v);
                if (io->delay_us) io->delay_us(io->cookie, 1);
                uint32_t st = 0;
                for (r->cx_tries = 1; !bad && r->cx_tries <= GPB_GDSC_POLL_TRIES; ++r->cx_tries) {
                    if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GDS_HW_CTRL, &st)) {bad = 1; break;}
                    if (gpb_gdsc_on(st)) break;
                    if (io->delay_us) io->delay_us(io->cookie, 1);
                }
                r->cx_hwctrl_after = st;
                if (!bad && gpb_gdsc_on(st)) {
                    if (!(v & GPB_GDSC_RETAIN_FF)) {++r->writes; bad |= io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, v | GPB_GDSC_RETAIN_FF);}
                    if (io->delay_us) io->delay_us(io->cookie, 2);
                    r->powered_cx = !bad;
                }
            }
            gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, &r->cx_after);
            r->cx_gdscr = r->cx_after; r->cx_hwctrl = r->cx_hwctrl_after;
        }
        if (r->powered_cx) {
            uint32_t a = 0, c = 0;
            bad |= gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_AHB_CLK, &a);
            ++r->writes; bad |= io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_AHB_CLK, a | GPB_CBCR_ENABLE);
            if (io->delay_us) io->delay_us(io->cookie, GPB_BRANCH_HALT_DELAY_US);
            bad |= gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_SMMU_VOTE_CLK, &c);
            ++r->writes; bad |= io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_SMMU_VOTE_CLK, c | GPB_CBCR_ENABLE);
            for (unsigned waited = 0; !bad; waited += 10) {
                if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_SMMU_VOTE_CLK, &r->cc_smmu)) {bad = 1; break;}
                if (gpb_clock_on(r->cc_smmu) || waited >= GPB_VOTE_POLL_US) break;
                if (io->delay_us) io->delay_us(io->cookie, 10);
            }
            gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_AHB_CLK, &r->cc_ahb);
            r->powered_clocks = !bad && gpb_clock_on(r->cc_smmu);
        }
        if (bad) r->io_error = 1;
    }
    // Stage 3: the GPU SMMU needs the CX domain and its vote clock (as sheng and uke gate it; the 3a's kgsl-smmu node lists that
    // clock). CX counts as on when either GDSCR or its hw-ctrl status shows PWR_ON. Global space 0 only.
    const int cx_on = gpb_gdsc_on(r->cx_gdscr) || gpb_gdsc_on(r->cx_hwctrl);
    if (!(have & (1u << GPB_WIN_SMMU))) r->smmu = GPB_NOMAP;
    else if (r->cc != GPB_DONE || !cx_on || !gpb_clock_on(r->cc_smmu)) r->smmu = GPB_SKIPPED_PREREQ;
    else if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GMU_CLK, &r->gate_gmu) || !gpb_clock_on(r->gate_gmu)) {r->smmu = GPB_SKIPPED_PREREQ; r->smmu_why = 1;}
    else if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_HUB_CX_INT_CLK, &r->gate_hub) || !gpb_clock_on(r->gate_hub)) {r->smmu = GPB_SKIPPED_PREREQ; r->smmu_why = 2;}
    else if (gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_SNOC_DVM_GFX, &r->gate_dvm) || !gpb_clock_on(r->gate_dvm)) {r->smmu = GPB_SKIPPED_PREREQ; r->smmu_why = 3;}
    else {
        if (io->stage) io->stage(io->cookie, GPB_WIN_SMMU);
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_SCR0, &r->scr0);
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_ID0, &r->id0);
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_ID1, &r->id1);
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_ID2, &r->id2);
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_GFSR, &r->gfsr);
        // Every stream match entry and its S2CR, read only: which streams the bootloader or hypervisor already routes.
        r->num_smr = r->id0 & 0xff;
        if (r->num_smr > GPB_SMMU_MAX_SMR) r->num_smr = GPB_SMMU_MAX_SMR;
        for (unsigned i = 0; i < r->num_smr; ++i) {
            if (gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_SMR(i), &r->smr[i])) break;
            gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_S2CR(i), &r->s2cr[i]);
            if (r->smr[i] & GPB_SMMU_SMR_VALID) ++r->smr_valid;
        }
        r->smmu = GPB_DONE;
    }
    // Stage 4: the GPU register window needs CX and GX on. GX is GMU-owned on gen8, so before the GMU runs this stays skipped.
    if (!(have & (1u << GPB_WIN_GPU))) r->gpu = GPB_NOMAP;
    else if (r->cc != GPB_DONE || !cx_on || !gpb_gdsc_on(r->gx_gdscr)) r->gpu = GPB_SKIPPED_PREREQ;
    else {
        if (io->stage) io->stage(io->cookie, GPB_WIN_GPU);
        gpb_rd(io, r, GPB_WIN_GPU, GPB_RBBM_STATUS_BYTES, &r->rbbm_status);
        r->gpu = GPB_DONE;
    }
}
#endif
