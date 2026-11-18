/*
 * ruan (iPadOS/UniXNU): HakiOS drivers/input/hakios.focaltech.c, unchanged but for the CPACR FP enable (kernel code here is
 * general-registers-only) and the header; events go to RuanInput.c (NativeHidInput). Original header:
 * The touch screen of the POCO X6 5G (Garnet): FocalTech FT3683G on the SPI bus of the SoC's
 * serial engine 3 (QUP1 SE3), as a source of touches for /dev/hakios-touch (sys/hakios.input.h).
 * Only with boot-arg touchscreen=1 or garnet_touch=1.
 */
#include <kern/clock.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include "RuanInputShim.h"
#include <sys/systm.h>

#define printf(...) do {} while (0)

extern void hakios_tl(const char *format, ...) __printflike(1, 2);
extern void loader_log_line(const char *line);

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern vm_offset_t ml_io_map_wcomb(vm_offset_t phys_addr, vm_size_t size);
extern kern_return_t thread_terminate(thread_t thread);

static void
append_hex8(char *buf, uint32_t *pos, uint8_t val)
{
	static const char hex[] = "0123456789abcdef";
	buf[(*pos)++] = hex[(val >> 4) & 0xf];
	buf[(*pos)++] = hex[val & 0xf];
}

static void
append_hex32(char *buf, uint32_t *pos, uint32_t val)
{
	append_hex8(buf, pos, (uint8_t)(val >> 24));
	append_hex8(buf, pos, (uint8_t)(val >> 16));
	append_hex8(buf, pos, (uint8_t)(val >> 8));
	append_hex8(buf, pos, (uint8_t)val);
}

static void
append_str(char *buf, uint32_t *pos, const char *s)
{
	while (*s) {
		buf[(*pos)++] = *s++;
	}
}

static vm_offset_t tlmm, gcc, se, rsc, cmd_db;

static inline uint32_t
rd(vm_offset_t address)
{
	return *(volatile uint32_t *)address;
}

static inline void
wr(vm_offset_t address, uint32_t value)
{
	*(volatile uint32_t *)address = value;
}

static void
sleep_us(uint32_t us)
{
	delay_for_interval(us, NSEC_PER_USEC);
}

static void
sleep_ms(uint32_t ms)
{
	delay_for_interval(ms, NSEC_PER_MSEC);
}

/* ---- pins (TLMM) ------------------------------------------------------------------------------- */

#define TLMM_PHYS               0x0f100000UL    /* POCO X6 5G (garnet / SM7435-AB) TLMM GPIO base */
#define TLMM_SIZE               0x100000UL
#define GPIO_CFG(n)             (tlmm + 0x1000UL * (n))         /* [1:0] pull, [5:2] function, [8:6] drive, [9] output */
#define GPIO_IO(n)              (tlmm + 0x1000UL * (n) + 4)     /* bit 0 in, bit 1 out */
#define PULL_NONE               0
#define PULL_UP                 3

#define PIN_MISO                10      /* QUP1 SE3 SPI MISO */
#define PIN_MOSI                11      /* QUP1 SE3 SPI MOSI */
#define PIN_CLK                 12      /* QUP1 SE3 SPI CLK */
#define PIN_CS                  13      /* QUP1 SE3 SPI CS */
#define PIN_INT                 98      /* low = the chip has a report (active low) */
#define PIN_RESET               96      /* low = in reset (active low) */
#define PIN_AVDD                0       /* managed by UEFI / PMIC on Garnet */
#define PIN_FUNCTION_SPI        1       /* "qup1_se3" */

static void
gpio_configure(unsigned pin, unsigned function, unsigned pull, unsigned ma, bool output)
{
	wr(GPIO_CFG(pin), (pull & 3) | ((function & 0xf) << 2) | (((ma / 2 - 1) & 7) << 6) | (output ? (1u << 9) : 0));
}

static void
gpio_set(unsigned pin, bool high)
{
	wr(GPIO_IO(pin), high ? 2 : 0);
}

static bool
gpio_get(unsigned pin)
{
	return (rd(GPIO_IO(pin)) & 1) != 0;
}

static void
gpio_output(unsigned pin, bool high, unsigned pull, unsigned ma)
{
	gpio_set(pin, high);            /* the level first, so that the pin never drives the wrong one */
	gpio_configure(pin, 0, pull, ma, true);
}

/* ---- the I/O supply (RPMh) ----------------------------------------------------------------------- */

#define CMD_DB_PHYS             0x80860000UL
#define CMD_DB_SIZE             0x20000UL
#define RSC_PHYS                0x17a20000UL    /* Garnet (SM7435): the application processor's "DRV 2" */
#define RSC_SIZE                0x10000UL
#define TCS(reg)                (rsc + 0xd00 + (reg))           /* command slot set 0, an "active" one */
#define TCS_IRQ_ENABLE          0x00
#define TCS_IRQ_STATUS          0x04
#define TCS_IRQ_CLEAR           0x08
#define TCS_WAIT_FOR_COMPLETION 0x10
#define TCS_CONTROL             0x14
#define TCS_CONTROL_ENABLE      (1u << 16)
#define TCS_CONTROL_TRIGGER     (1u << 24)
#define TCS_STATUS              0x18            /* 0 while busy */
#define TCS_CMD_ENABLE          0x1c
#define TCS_CMD_MSGID(n)        (0x30 + 20 * (n))
#define TCS_CMD_ADDR(n)         (0x34 + 20 * (n))
#define TCS_CMD_DATA(n)         (0x38 + 20 * (n))
#define MSGID_WRITE_4_BYTES     0x10008
#define MSGID_RESPONSE          0x100

#define VRM_VOLTAGE             0               /* a regulator's registers, from its address: millivolts */
#define VRM_ENABLE              4
#define VRM_MODE                8
#define VRM_MODE_LDO_HPM        7

struct cmd_db_slave {
	uint16_t id, header_offset, data_offset, count, version, reserved[3];
};
struct cmd_db_header {
	uint32_t version;
	uint8_t magic[4];
	struct cmd_db_slave slave[8];
	uint32_t checksum, reserved;
	uint8_t data[];
};
struct cmd_db_entry {
	char id[8];
	uint32_t priority[2];
	uint32_t address;
	uint16_t length, offset;
};

/* The RPMh address of a resource by its name in the command database the boot loader left; 0 = none. */
static uint32_t
rpmh_address(const char *name)
{
	if (!cmd_db) {
		return 0;
	}
	const struct cmd_db_header *db = (const struct cmd_db_header *)cmd_db;
	char id[8] = { 0 };

	if (db->magic[0] != 0xdb || db->magic[1] != 0x30 || db->magic[2] != 0x03 || db->magic[3] != 0x0c) {
		char msg[64];
		uint32_t pos = 0;
		append_str(msg, &pos, "focaltech: no command database (magic ");
		append_hex8(msg, &pos, db->magic[0]);
		append_hex8(msg, &pos, db->magic[1]);
		append_hex8(msg, &pos, db->magic[2]);
		append_hex8(msg, &pos, db->magic[3]);
		append_str(msg, &pos, ")\n");
		msg[pos] = 0;
		loader_log_line(msg);
		return 0;
	}
	strlcpy(id, name, sizeof(id));
	for (unsigned s = 0; s < 8; s++) {
		const struct cmd_db_slave *slave = &db->slave[s];
		const struct cmd_db_entry *entry = (const struct cmd_db_entry *)(db->data + slave->header_offset);

		if (slave->id == 0 || slave->header_offset >= CMD_DB_SIZE - 0x1000 || slave->count > 512) {
			continue;
		}
		for (unsigned i = 0; i < slave->count; i++) {
			if (memcmp(entry[i].id, id, sizeof(id)) == 0) {
				return entry[i].address;
			}
		}
	}
	return 0;
}

static bool
rpmh_wait(uint32_t reg, uint32_t mask, uint32_t value, const char *what)
{
	for (int i = 0; i < 2000; i++) {
		if ((rd(TCS(reg)) & mask) == value) {
			return true;
		}
		sleep_us(100);
	}
	char msg[80];
	uint32_t pos = 0;
	append_str(msg, &pos, "focaltech: RPMh: timeout waiting for ");
	append_str(msg, &pos, what);
	append_str(msg, &pos, " (reg 0x");
	append_hex32(msg, &pos, reg);
	append_str(msg, &pos, " = 0x");
	append_hex32(msg, &pos, rd(TCS(reg)));
	append_str(msg, &pos, ")\n");
	msg[pos] = 0;
	loader_log_line(msg);
	return false;
}

/* Send up to three register writes to RPMh and wait until they are done. */
static bool
rpmh_write(const uint32_t *address, const uint32_t *data, unsigned count)
{
	uint32_t irq_enable = rd(TCS(TCS_IRQ_ENABLE));
	bool done;

	/* the slot set must be idle, and switched off the way the hardware wants it: trigger, then enable */
	for (int i = 0; rd(TCS(TCS_STATUS)) == 0; i++) {
		if (i > 2000) {
			loader_log_line("focaltech: RPMh: the command slots stay busy\n");
			return false;
		}
		sleep_us(100);
	}
	wr(TCS(TCS_CONTROL), rd(TCS(TCS_CONTROL)) & ~TCS_CONTROL_TRIGGER);
	wr(TCS(TCS_CONTROL), rd(TCS(TCS_CONTROL)) & ~TCS_CONTROL_ENABLE);
	wr(TCS(TCS_IRQ_CLEAR), 1);
	for (unsigned i = 0; i < count; i++) {
		wr(TCS(TCS_CMD_MSGID(i)), MSGID_WRITE_4_BYTES | MSGID_RESPONSE);
		wr(TCS(TCS_CMD_ADDR(i)), address[i]);
		wr(TCS(TCS_CMD_DATA(i)), data[i]);
	}
	wr(TCS(TCS_WAIT_FOR_COMPLETION), (1u << count) - 1);
	wr(TCS(TCS_CMD_ENABLE), (1u << count) - 1);
	wr(TCS(TCS_IRQ_ENABLE), irq_enable | 1);        /* the status bit follows the enable; the interrupt itself stays masked */
	wr(TCS(TCS_CONTROL), TCS_CONTROL_ENABLE);
	wr(TCS(TCS_CONTROL), TCS_CONTROL_ENABLE | TCS_CONTROL_TRIGGER);

	done = rpmh_wait(TCS_IRQ_STATUS, 1, 1, "the request");
	wr(TCS(TCS_CONTROL), rd(TCS(TCS_CONTROL)) & ~TCS_CONTROL_TRIGGER);
	wr(TCS(TCS_CONTROL), rd(TCS(TCS_CONTROL)) & ~TCS_CONTROL_ENABLE);
	wr(TCS(TCS_CMD_ENABLE), 0);
	wr(TCS(TCS_WAIT_FOR_COMPLETION), 0);
	wr(TCS(TCS_IRQ_CLEAR), 1);
	wr(TCS(TCS_IRQ_ENABLE), irq_enable);
	return done;
}

/* The chip's power supply: ldoe9 (AVDD 3.224 V) via RPMh VRM and touch_vddio (1.8 V) via PMIC SPMI */
static bool
io_supply_on(void)
{
	loader_log_line("focaltech: io_supply_on: enabling ldoe9 (AVDD 3.224V) and touch_vddio (1.8V)...\n");
	garnet_enable_touch_vddio();
	if (!rsc || !cmd_db) {
		loader_log_line("focaltech: rsc or cmd_db not mapped!\n");
		return false;
	}
	uint32_t base = rpmh_address("ldoe9");
	if (base == 0) {
		base = rpmh_address("pm6150l_l9");
	}
	if (base == 0) {
		loader_log_line("focaltech: RPMh: \"ldoe9\" not found in cmd_db! Available entries:\n");
		const struct cmd_db_header *db = (const struct cmd_db_header *)cmd_db;
		for (unsigned s = 0; s < 8; s++) {
			const struct cmd_db_slave *slave = &db->slave[s];
			const struct cmd_db_entry *entry = (const struct cmd_db_entry *)(db->data + slave->header_offset);
			if (slave->id == 0 || slave->header_offset >= CMD_DB_SIZE - 0x1000 || slave->count > 512)
				continue;
			for (unsigned i = 0; i < slave->count; i++) {
				char emsg[32];
				uint32_t epos = 0;
				append_str(emsg, &epos, "  ");
				for (int k = 0; k < 8 && entry[i].id[k]; k++) {
					emsg[epos++] = entry[i].id[k];
				}
				append_str(emsg, &epos, " -> 0x");
				append_hex32(emsg, &epos, entry[i].address);
				append_str(emsg, &epos, "\n");
				emsg[epos] = 0;
				loader_log_line(emsg);
			}
		}
		return false;
	}

	if ((base >> 16 & 0xf) != 4) {
		char msg[80];
		uint32_t pos = 0;
		append_str(msg, &pos, "focaltech: RPMh: ldoe9 address not VRM (0x");
		append_hex32(msg, &pos, base);
		append_str(msg, &pos, ")\n");
		msg[pos] = 0;
		loader_log_line(msg);
		return false;
	}

	char msg[80];
	uint32_t pos = 0;
	append_str(msg, &pos, "focaltech: RPMh: ldoe9 is at 0x");
	append_hex32(msg, &pos, base);
	append_str(msg, &pos, "\n");
	msg[pos] = 0;
	loader_log_line(msg);

	uint32_t address[3] = { base + VRM_VOLTAGE, base + VRM_ENABLE, base + VRM_MODE };
	uint32_t data[3] = { 3224, 1, VRM_MODE_LDO_HPM };

	if (!rpmh_write(address, data, 3)) {
		loader_log_line("focaltech: RPMh: write to ldoe9 failed\n");
		return false;
	}
	loader_log_line("focaltech: ldoe9 supply on (3.224 V)\n");
	return true;
}

/* ---- clocks (GCC) -------------------------------------------------------------------------------- */

#define GCC_PHYS                0x00100000UL    /* POCO X6 5G (garnet / SM7435-AB) GCC */
#define GCC_SIZE                0x40000UL
#define GCC_QUP1_WRAP_M_AHB_CBCR (gcc + 0x28004)
#define GCC_QUP1_WRAP_S_AHB_CBCR (gcc + 0x28008)
#define GCC_QUP1_SE3_CBCR       (gcc + 0x283a8)
#define GCC_QUP1_SE3_CMD_RCGR   (gcc + 0x283b0)
#define GCC_QUP1_SE3_CFG_RCGR   (gcc + 0x283b4)
#define CLOCK_OFF               (1u << 31)
#define XO_HZ                   19200000

static uint32_t se_source_hz, se_clock_select;

static bool
clocks_on(void)
{
	if (!gcc) {
		return false;
	}
	/* Enable M_AHB and S_AHB for QUP1 */
	wr(GCC_QUP1_WRAP_M_AHB_CBCR, rd(GCC_QUP1_WRAP_M_AHB_CBCR) | 1);
	wr(GCC_QUP1_WRAP_S_AHB_CBCR, rd(GCC_QUP1_WRAP_S_AHB_CBCR) | 1);

	/* Check if SE3 branch clock is off (bit 31 is CLK_OFF) */
	if (rd(GCC_QUP1_SE3_CBCR) & CLOCK_OFF) {
		/* Configure RCG to XO (19.2 MHz, source 0, div 0) */
		wr(GCC_QUP1_SE3_CFG_RCGR, (rd(GCC_QUP1_SE3_CFG_RCGR) & ~0x371fu));
		wr(GCC_QUP1_SE3_CMD_RCGR, rd(GCC_QUP1_SE3_CMD_RCGR) | 1);
		for (int i = 0; i < 500 && (rd(GCC_QUP1_SE3_CMD_RCGR) & 1); i++) {
			sleep_us(10);
		}
		/* Turn on branch clock */
		wr(GCC_QUP1_SE3_CBCR, rd(GCC_QUP1_SE3_CBCR) | 1);
		for (int i = 0; i < 1000 && (rd(GCC_QUP1_SE3_CBCR) & CLOCK_OFF); i++) {
			sleep_us(10);
		}
		se_source_hz = XO_HZ;
		se_clock_select = 0;
	} else {
		/* Clock was already running from UEFI */
		uint32_t cfg = rd(GCC_QUP1_SE3_CFG_RCGR);
		uint32_t src = (cfg >> 8) & 7;
		se_clock_select = src;
		se_source_hz = (src == 0) ? XO_HZ : 100000000;
	}
	return true;
}

/* ---- SPI through the serial engine (GENI) ---------------------------------------------------------- */

#define SE_PHYS                 0x00a8c000UL    /* POCO X6 5G (garnet) QUP1 SE3 SPI controller */
#define SE_SIZE                 0x4000UL
#define GENI_FORCE_DEFAULT      (se + 0x020)
#define GENI_OUTPUT_CTRL        (se + 0x024)
#define GENI_CGC_CTRL           (se + 0x028)
#define GENI_STATUS             (se + 0x040)    /* bit 0: a command is running */
#define GENI_SER_M_CLK_CFG      (se + 0x048)    /* bit 0 enable, [15:4] divider */
#define GENI_IF_DISABLE_RO      (se + 0x064)    /* bit 0: no FIFO interface */
#define GENI_FW_REVISION_RO     (se + 0x068)    /* [15:8] protocol: 1 = SPI */
#define GENI_CLK_SEL            (se + 0x07c)
#define SPI_CPHA                (se + 0x224)
#define SPI_LOOPBACK            (se + 0x22c)
#define SPI_CPOL                (se + 0x230)
#define SPI_DEMUX_OUTPUT_INV    (se + 0x24c)
#define SPI_DEMUX_SEL           (se + 0x250)
#define GENI_BYTE_GRAN          (se + 0x254)
#define GENI_DMA_MODE_EN        (se + 0x258)
#define SPI_TRANS_CFG           (se + 0x25c)
#define GENI_TX_PACKING_CFG0    (se + 0x260)
#define GENI_TX_PACKING_CFG1    (se + 0x264)
#define SPI_WORD_LEN            (se + 0x268)
#define SPI_TX_TRANS_LEN        (se + 0x26c)
#define SPI_RX_TRANS_LEN        (se + 0x270)
#define SPI_DELAY_COUNTERS      (se + 0x278)
#define GENI_RX_PACKING_CFG0    (se + 0x284)
#define GENI_RX_PACKING_CFG1    (se + 0x288)
#define GENI_M_CMD0             (se + 0x600)    /* [31:27] operation */
#define GENI_M_CMD_CTRL         (se + 0x604)    /* bit 2 cancel, bit 1 abort */
#define GENI_M_IRQ_STATUS       (se + 0x610)
#define GENI_M_IRQ_EN           (se + 0x614)
#define GENI_M_IRQ_CLEAR        (se + 0x618)
#define GENI_S_IRQ_CLEAR        (se + 0x648)
#define GENI_TX_FIFO            (se + 0x700)
#define GENI_RX_FIFO            (se + 0x780)
#define GENI_TX_FIFO_STATUS     (se + 0x800)    /* [27:0] words */
#define GENI_RX_FIFO_STATUS     (se + 0x804)    /* bit 31 last, [30:28] bytes of the last word, [24:0] words */
#define GENI_TX_WATERMARK       (se + 0x80c)
#define GENI_RX_WATERMARK       (se + 0x810)
#define GENI_RX_RFR_WATERMARK   (se + 0x814)
#define SE_DMA_TX_IRQ_CLR       (se + 0xc44)
#define SE_DMA_RX_IRQ_CLR       (se + 0xd44)
#define SE_GSI_EVENT_EN         (se + 0xe18)
#define SE_IRQ_EN               (se + 0xe1c)
#define SE_HW_PARAM_0           (se + 0xe24)    /* [21:16] FIFO depth in words */
#define SE_DMA_GENERAL_CFG      (se + 0xe30)

#define M_CMD_DONE              (1u << 0)
#define M_CMD_CANCEL            (1u << 4)
#define M_CMD_ABORT             (1u << 5)
#define M_ERRORS                ((1u << 1) | (1u << 2) | (1u << 3) | (1u << 24) | (1u << 25) | (1u << 28) | (1u << 29))
#define SPI_FULL_DUPLEX         (3u << 27)

static uint32_t fifo_depth;

/* 0 = ready; otherwise why the engine cannot be used */
static const char *
geni_spi_init(uint32_t hz)
{
	uint32_t divider;
	uint32_t proto = (rd(GENI_FW_REVISION_RO) >> 8) & 0xff;

	char msg[64];
	uint32_t mpos = 0;
	append_str(msg, &mpos, "focaltech: geni proto=");
	append_hex8(msg, &mpos, (uint8_t)proto);
	msg[mpos++] = '\n';
	msg[mpos] = '\0';
	loader_log_line(msg);

	if (proto != 1) {
		return "the serial engine has no SPI firmware";
	}
	if (rd(GENI_IF_DISABLE_RO) & 1) {
		return "the serial engine's FIFO interface is disabled";
	}
	fifo_depth = rd(SE_HW_PARAM_0) >> 16 & 0x3f;
	mpos = 0;
	append_str(msg, &mpos, "focaltech: geni fifo=");
	append_hex8(msg, &mpos, (uint8_t)fifo_depth);
	msg[mpos++] = '\n';
	msg[mpos] = '\0';
	loader_log_line(msg);

	if (fifo_depth < 4) {
		return "the serial engine reports no FIFO";
	}
	wr(SE_GSI_EVENT_EN, 0);
	wr(GENI_M_IRQ_CLEAR, 0xffffffff);
	wr(GENI_S_IRQ_CLEAR, 0xffffffff);
	wr(SE_DMA_TX_IRQ_CLR, 0xffffffff);
	wr(SE_DMA_RX_IRQ_CLR, 0xffffffff);
	wr(GENI_CGC_CTRL, rd(GENI_CGC_CTRL) | 0x7f);
	wr(SE_DMA_GENERAL_CFG, rd(SE_DMA_GENERAL_CFG) | 0xf);
	wr(GENI_OUTPUT_CTRL, 0x7f);
	wr(GENI_FORCE_DEFAULT, 1);
	wr(GENI_DMA_MODE_EN, rd(GENI_DMA_MODE_EN) & ~1u);
	wr(GENI_RX_WATERMARK, fifo_depth - 3);
	wr(GENI_RX_RFR_WATERMARK, fifo_depth - 2);
	wr(GENI_TX_WATERMARK, 0);
	/* the status bits we poll follow these enables; the interrupt itself stays masked at the GIC */
	wr(SE_IRQ_EN, rd(SE_IRQ_EN) | 0xf);
	wr(GENI_M_IRQ_EN, rd(GENI_M_IRQ_EN) | 0x7fc0007f);

	/* mode 0, chip select 0, 8 bits, most significant first, four bytes in a FIFO word */
	wr(SPI_LOOPBACK, 0);
	wr(SPI_DEMUX_SEL, 0);
	wr(SPI_CPHA, 0);
	wr(SPI_CPOL, 0);
	wr(SPI_DEMUX_OUTPUT_INV, 0);
	wr(SPI_TRANS_CFG, rd(SPI_TRANS_CFG) & ~2u);
	wr(SPI_DELAY_COUNTERS, 0);
	wr(GENI_TX_PACKING_CFG0, 0x0007f8fe);
	wr(GENI_TX_PACKING_CFG1, 0x000ffefe);
	wr(GENI_RX_PACKING_CFG0, 0x0007f8fe);
	wr(GENI_RX_PACKING_CFG1, 0x000ffefe);
	wr(GENI_BYTE_GRAN, 0);
	wr(SPI_WORD_LEN, 8 - 4);

	divider = (se_source_hz + hz - 1) / hz;
	wr(GENI_CLK_SEL, se_clock_select & 7);
	wr(GENI_SER_M_CLK_CFG, (divider ? divider : 1) << 4 | 1);
	return NULL;
}

static void
geni_drain(uint8_t *rx, uint32_t length, uint32_t *received)
{
	uint32_t status = rd(GENI_RX_FIFO_STATUS), words = status & 0x01ffffff, bytes = words * 4;

	if (status & 0x80000000u) {
		uint32_t valid = status >> 28 & 7;

		if (valid && valid < 4) {
			bytes -= 4 - valid;
		}
	}
	for (uint32_t i = 0; i < words; i++) {
		uint32_t word = rd(GENI_RX_FIFO);

		for (int j = 0; j < 4 && bytes; j++, bytes--) {
			if (*received < length) {
				if (rx) {
					rx[*received] = (uint8_t)(word >> (8 * j));
				}
				(*received)++;
			}
		}
	}
}

static void
geni_recover(void)
{
	wr(GENI_M_CMD_CTRL, 1u << 2);
	for (int i = 0; i < 2000 && !(rd(GENI_M_IRQ_STATUS) & M_CMD_CANCEL); i++) {
		sleep_us(100);
	}
	if (!(rd(GENI_M_IRQ_STATUS) & M_CMD_CANCEL)) {
		wr(GENI_M_CMD_CTRL, 1u << 1);
		for (int i = 0; i < 2000 && !(rd(GENI_M_IRQ_STATUS) & M_CMD_ABORT); i++) {
			sleep_us(100);
		}
	}
	for (int i = 0; i < 64 && (rd(GENI_RX_FIFO_STATUS) & 0x01ffffff); i++) {
		(void)rd(GENI_RX_FIFO);
	}
	wr(GENI_M_IRQ_CLEAR, 0xffffffff);
}

/* One transfer with the chip selected throughout: `length` bytes out (zeros without tx) and as many in. */
static bool
geni_transfer(const uint8_t *tx, uint8_t *rx, uint32_t length)
{
	static unsigned complaints;
	uint32_t sent = 0, received = 0, status = 0;
	uint64_t deadline;

	for (int i = 0; rd(GENI_STATUS) & 1; i++) {
		if (i > 2000) {
			geni_recover();
			break;
		}
		sleep_us(100);
	}
	wr(GENI_M_IRQ_CLEAR, 0xffffffff);
	wr(SPI_TX_TRANS_LEN, length);
	wr(SPI_RX_TRANS_LEN, length);
	wr(GENI_M_CMD0, SPI_FULL_DUPLEX);
	clock_interval_to_deadline(200, NSEC_PER_MSEC, &deadline);
	while (mach_absolute_time() < deadline) {
		while (sent < length && (rd(GENI_TX_FIFO_STATUS) & 0x0fffffff) + 1 < fifo_depth) {
			uint32_t word = 0;

			for (int j = 0; j < 4 && sent < length; j++, sent++) {
				word |= (uint32_t)(tx ? tx[sent] : 0) << (8 * j);
			}
			wr(GENI_TX_FIFO, word);
		}
		status = rd(GENI_M_IRQ_STATUS);
		geni_drain(rx, length, &received);
		if (status & M_ERRORS) {
			break;
		}
		if (status & M_CMD_DONE) {
			geni_drain(rx, length, &received);
			wr(GENI_M_IRQ_CLEAR, status);
			if (received == length) {
				return true;
			}
			break;
		}
	}
	if (complaints++ < 8) {
		printf("focaltech: SPI transfer of %u bytes failed: status %#x, sent %u, received %u\n", length, status, sent,
		    received);
	}
	geni_recover();
	return false;
}

/* ---- SPI by hand, on the same pins ----------------------------------------------------------------- */

static unsigned bitbang_in = PIN_MISO, bitbang_out = PIN_MOSI;

static void
bitbang_init(void)
{
	gpio_output(PIN_CS, true, PULL_NONE, 6);
	gpio_output(PIN_CLK, false, PULL_NONE, 6);
	gpio_output(bitbang_out, false, PULL_NONE, 6);
	gpio_configure(bitbang_in, 0, PULL_NONE, 6, false);
	sleep_ms(1);

	char pmsg[96];
	uint32_t ppos = 0;
	append_str(pmsg, &ppos, "focaltech: bitbang_init in=");
	append_hex8(pmsg, &ppos, (uint8_t)bitbang_in);
	append_str(pmsg, &ppos, " out=");
	append_hex8(pmsg, &ppos, (uint8_t)bitbang_out);
	append_str(pmsg, &ppos, " cfg=");
	append_hex8(pmsg, &ppos, (uint8_t)(rd(GPIO_CFG(bitbang_in)) >> 8));
	append_hex8(pmsg, &ppos, (uint8_t)rd(GPIO_CFG(bitbang_in)));
	append_str(pmsg, &ppos, " io=");
	append_hex8(pmsg, &ppos, (uint8_t)rd(GPIO_IO(bitbang_in)));
	pmsg[ppos++] = '\n';
	pmsg[ppos] = '\0';
	loader_log_line(pmsg);
}

static bool
bitbang_transfer(const uint8_t *tx, uint8_t *rx, uint32_t length)
{
	gpio_set(PIN_CS, false);
	sleep_us(5);
	for (uint32_t i = 0; i < length; i++) {
		uint8_t out = tx ? tx[i] : 0, in = 0;

		for (int bit = 7; bit >= 0; bit--) {
			gpio_set(bitbang_out, (out >> bit) & 1);
			sleep_us(1);
			gpio_set(PIN_CLK, true);
			sleep_us(1);
			in = (uint8_t)((in << 1) | (gpio_get(bitbang_in) ? 1 : 0));
			gpio_set(PIN_CLK, false);
		}
		if (rx) {
			rx[i] = in;
		}
	}
	sleep_us(5);
	gpio_set(PIN_CS, true);
	sleep_us(50);
	return true;
}

/* The same, without a sleep per bit: XNU's sleep_us(1) is a timer and a context switch, which held chip select low
 * for milliseconds per short read. The register writes themselves pace the clock (about 1-3 MHz, the chip takes
 * 9.6); mode 0: data changes while the clock is low, sampled on the rising edge. ruan's NT36532 resets itself
 * (0xFD in its event buffer) when transfers drag on. */
static bool
bitbang_fast_transfer(const uint8_t *tx, uint8_t *rx, uint32_t length)
{
	vm_offset_t clk = GPIO_IO(PIN_CLK), out = GPIO_IO(bitbang_out), in_reg = GPIO_IO(bitbang_in);
	gpio_set(PIN_CS, false);
	(void)rd(clk);
	for (uint32_t i = 0; i < length; i++) {
		uint8_t o = tx ? tx[i] : 0, v = 0;
		for (int bit = 7; bit >= 0; bit--) {
			wr(out, ((o >> bit) & 1) ? 2 : 0);
			(void)rd(out);                          /* let the level settle before the edge */
			wr(clk, 2);
			(void)rd(clk);
			v = (uint8_t)((v << 1) | (rd(in_reg) & 1));
			wr(clk, 0);
		}
		if (rx) {
			rx[i] = v;
		}
	}
	(void)rd(clk);
	gpio_set(PIN_CS, true);
	return true;
}

static bool (*spi_transfer)(const uint8_t *tx, uint8_t *rx, uint32_t length);

/* ---- the Goodix chip ------------------------------------------------------------------------------- */

#define GOODIX_FW_VERSION       0x10014         /* 28 bytes */
#define GOODIX_IC_INFO          0x10070         /* a 16-bit length, then that many bytes */
#define GOODIX_MAX_READ         1024
#define GOODIX_MAX_TOUCHES      10
#define GOODIX_STATUS_TOUCH     0x80
#define GOODIX_STATUS_REQUEST   0x40
#define GOODIX_REQUEST_RESET    3

static uint8_t spi_tx[8 + GOODIX_MAX_READ], spi_rx[8 + GOODIX_MAX_READ];
static uint32_t touch_address, command_address;
static const char *report_rate = "240";        /* what the status line says (touch_rate=480) */
static uint32_t max_x = 10800, max_y = 24000;   /* the device tree's; the chip may say otherwise */

static bool
goodix_read(uint32_t address, uint8_t *data, uint32_t length)
{
	if (length > GOODIX_MAX_READ) {
		return false;
	}
	spi_tx[0] = 0xf1;
	spi_tx[1] = (uint8_t)(address >> 24);
	spi_tx[2] = (uint8_t)(address >> 16);
	spi_tx[3] = (uint8_t)(address >> 8);
	spi_tx[4] = (uint8_t)address;
	spi_tx[5] = spi_tx[6] = spi_tx[7] = 0xff;
	memset(spi_tx + 8, 0, length);
	if (!spi_transfer(spi_tx, spi_rx, 8 + length)) {
		return false;
	}
	memcpy(data, spi_rx + 8, length);
	return true;
}

static bool
goodix_write(uint32_t address, const uint8_t *data, uint32_t length)
{
	if (length > GOODIX_MAX_READ) {
		return false;
	}
	spi_tx[0] = 0xf0;
	spi_tx[1] = (uint8_t)(address >> 24);
	spi_tx[2] = (uint8_t)(address >> 16);
	spi_tx[3] = (uint8_t)(address >> 8);
	spi_tx[4] = (uint8_t)address;
	memcpy(spi_tx + 5, data, length);
	return spi_transfer(spi_tx, NULL, 5 + length);
}

/* The chip's blocks end in the 16-bit sum of their bytes; all zeros or all ones is no answer at all. */
static bool
goodix_checksum_ok(const uint8_t *data, uint32_t length)
{
	uint32_t sum = 0;
	bool blank = true;

	if (length < 2) {
		return false;
	}
	for (uint32_t i = 0; i < length - 2; i++) {
		sum += data[i];
		blank &= data[i] == 0 || data[i] == 0xff;
	}
	return !blank && (uint16_t)sum == (uint16_t)(data[length - 2] | data[length - 1] << 8);
}

static uint16_t
le16(const uint8_t *p)
{
	return (uint16_t)(p[0] | p[1] << 8);
}

static uint32_t
le32(const uint8_t *p)
{
	return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24;
}

static void
touch_reset(void)
{
	gpio_set(PIN_RESET, false);
	sleep_ms(2);
	gpio_set(PIN_RESET, true);
	sleep_ms(100);
}

/* Is the chip there and running its firmware? Finds where it keeps the touch report. */
static bool
goodix_probe(bool verbose)
{
	static uint8_t info[GOODIX_MAX_READ];
	uint8_t version[28];
	uint32_t length, offset;

	if (!goodix_read(GOODIX_FW_VERSION, version, sizeof(version))) {
		return false;
	}
	if (!goodix_checksum_ok(version, sizeof(version))) {
		if (verbose) {
			printf("focaltech: no valid firmware version: %02x %02x %02x %02x %02x %02x %02x %02x ... %02x %02x\n",
			    version[0], version[1], version[2], version[3], version[4], version[5], version[6], version[7],
			    version[26], version[27]);
		}
		return false;
	}
	printf("focaltech: chip \"%.6s\", firmware \"%.8s\" %02x.%02x.%02x.%02x, sensor %u\n", (const char *)version,
	    (const char *)version + 10, version[18], version[19], version[20], version[21], version[23]);

	if (!goodix_read(GOODIX_IC_INFO, info, 2)) {
		return false;
	}
	length = le16(info);
	if (length < 40 || length >= GOODIX_MAX_READ || !goodix_read(GOODIX_IC_INFO, info, length) ||
	    !goodix_checksum_ok(info, length)) {
		printf("focaltech: bad chip description (length %u)\n", length);
		return false;
	}
	/* the length, the version (16 bytes), the features (10), four counts, then five lists of 16-bit numbers */
	offset = 2 + 16 + 10 + 4;
	for (int i = 0; i < 5; i++) {
		if (offset >= length) {
			return false;
		}
		offset += 1 + 2u * info[offset];
	}
	if (offset + 48 + 2 > length) {
		printf("focaltech: chip description too short (%u, lists end at %u)\n", length, offset);
		return false;
	}
	touch_address = le32(info + offset + 44);
	command_address = le32(info + offset + 0);      /* (the "misc" part: the command buffer comes first) */
	if (offset + 122 + 20 + 2 <= length) {
		uint16_t x = le16(info + offset + 122 + 16), y = le16(info + offset + 122 + 18);

		if (x && y) {
			max_x = x;
			max_y = y;
		}
	}
	printf("focaltech: touch report at %#x, coordinates up to %u x %u\n", touch_address, max_x, max_y);
	return touch_address != 0;
}

/*
 * A command to the chip (Android's brl_send_cmd(): goodix_brl_hw.c of the phone's kernel): sixteen
 * bytes at the command address -- state, acknowledgement, length, command, its data, and the sum of
 * the bytes from the length on -- then the acknowledgement looked for, 0x80 when done.
 */
#define GOODIX_CMD_HIGH_RATE    0xc0            /* data 1: report 480 times a second instead of 240 (Xiaomi's game mode) */
#define GOODIX_ACK_OK           0x80
#define GOODIX_ACK_BUSY         0x02

static bool
goodix_command(uint8_t command, uint8_t data)
{
	uint8_t buffer[16], answer[16];
	uint32_t sum;

	if (command_address == 0) {
		return false;
	}
	memset(buffer, 0, sizeof(buffer));
	buffer[2] = 5;
	buffer[3] = command;
	buffer[4] = data;
	sum = buffer[2] + buffer[3] + buffer[4];
	buffer[5] = (uint8_t)sum;
	buffer[6] = (uint8_t)(sum >> 8);
	for (int attempt = 0; attempt < 6; attempt++) {
		if (!goodix_write(command_address, buffer, sizeof(buffer))) {
			return false;
		}
		for (int look = 0; look < 6; look++) {
			if (!goodix_read(command_address, answer, sizeof(answer))) {
				return false;
			}
			if (answer[1] == GOODIX_ACK_OK) {
				return true;
			}
			sleep_ms(1);
			if (answer[1] != GOODIX_ACK_BUSY && answer[1] != 0) {
				break;
			}
		}
	}
	return false;
}

/* What has been seen so far: said once a minute, so that the end of the log always tells. */
static struct {
	uint32_t polls, reports, touches, bad, last_x, last_y;
} seen;

/* Which fingers were down in the last report, and where. */
static struct {
	bool down, seen;
	uint32_t x, y;
} contact[GOODIX_MAX_TOUCHES];
static uint32_t flip;           /* boot-arg touch_flip: 1 = mirror left-right, 2 = mirror top-bottom */
static uint32_t swap_axes;      /* boot-arg touch_swap: 1 = swap X and Y axes */

static void
goodix_report(const uint8_t *touches, uint32_t count)
{
	static unsigned shown;

	for (int i = 0; i < GOODIX_MAX_TOUCHES; i++) {
		contact[i].seen = false;
	}
	for (uint32_t i = 0; i < count; i++) {
		const uint8_t *t = touches + 8 * i;
		uint32_t id = t[0] >> 4, kind = t[0] & 0xf;
		uint32_t x = le16(t + 2), y = le16(t + 4);

		if (id >= GOODIX_MAX_TOUCHES || kind == 1 || kind == 3) {       /* 1 and 3: a stylus */
			continue;
		}
		if (shown < 40) {
			shown++;
			printf("focaltech: finger %u at %u, %u (of %u x %u)\n", id, x, y, max_x, max_y);
		}
		seen.touches++;
		seen.last_x = x;
		seen.last_y = y;
		x = x >= max_x ? 65535 : x * 65535 / max_x;
		y = y >= max_y ? 65535 : y * 65535 / max_y;
		if (flip & 1) {
			x = 65535 - x;
		}
		if (flip & 2) {
			y = 65535 - y;
		}
		contact[id].seen = true;
		if (!contact[id].down) {
			hakios_touch_post(HAKIOS_TOUCH_DOWN, id, x, y);
		} else if (contact[id].x != x || contact[id].y != y) {
			hakios_touch_post(HAKIOS_TOUCH_MOVE, id, x, y);
		}
		contact[id].down = true;
		contact[id].x = x;
		contact[id].y = y;
	}
	/* a finger that is no longer in the report has lifted */
	for (uint32_t id = 0; id < GOODIX_MAX_TOUCHES; id++) {
		if (contact[id].down && !contact[id].seen) {
			contact[id].down = false;
			hakios_touch_post(HAKIOS_TOUCH_UP, id, contact[id].x, contact[id].y);
		}
	}
}

/* Read the report if there is one, and tell the chip it has been read. */
static void
goodix_poll(void)
{
	static uint8_t report[8 + 8 * GOODIX_MAX_TOUCHES + 2];
	static unsigned bad;
	const uint8_t zero = 0;
	const uint32_t first = 8 + 8 * 2 + 2;           /* the header and two fingers: all there is, most of the time */
	uint32_t count;

	seen.polls++;
	if (!goodix_read(touch_address, report, first) || report[0] == 0) {
		return;
	}
	seen.reports++;
	count = report[2] & 0xf;
	if ((report[0] & GOODIX_STATUS_TOUCH) && count > 2 && count <= GOODIX_MAX_TOUCHES &&
	    !goodix_read(touch_address + 8, report + 8, 8 * count + 2)) {
		return;
	}
	goodix_write(touch_address, &zero, 1);
	if (!goodix_checksum_ok(report, 8)) {
		seen.bad++;
		if (bad++ < 8) {
			printf("focaltech: bad report header: %02x %02x %02x %02x %02x %02x %02x %02x\n", report[0], report[1],
			    report[2], report[3], report[4], report[5], report[6], report[7]);
		}
		return;
	}
	if (report[0] & GOODIX_STATUS_REQUEST) {
		if ((report[2] & 0xf) == GOODIX_REQUEST_RESET || report[2] == GOODIX_REQUEST_RESET) {
			printf("focaltech: the chip asks to be reset\n");
			touch_reset();
		}
		return;
	}
	if (!(report[0] & GOODIX_STATUS_TOUCH)) {
		return;
	}
	if (count > GOODIX_MAX_TOUCHES || (count && !goodix_checksum_ok(report + 8, count * 8 + 2))) {
		seen.bad++;
		if (bad++ < 8) {
			printf("focaltech: bad report (%u touches)\n", count);
		}
		return;
	}
	goodix_report(report + 8, count);
}

/* ---- the FocalTech FT3680 chip --------------------------------------------------------------------- */

/*
 * FTS 5.x SPI framing from sm8350-kernel-OKX drivers/input/touchscreen/focaltech_3680/
 * focaltech_spi.c (verbatim):
 *   TX[0] = register address (writebuf[0] / cmd[0])
 *   TX[1] = FOCALTECH_READ_CTRL (0xA0 = READ_CMD, CRC_EN set) or FOCALTECH_WRITE_CTRL (0x00)
 *   TX[2..3] = data length BE (for read: datalen; for write: writelen - 1)
 *   TX[4..6] = three dummy bytes (SPI_DUMMY_BYTE)
 *   TX[7..7+len-1] = write data (empty on read; chip drives MISO here)
 *   TX[last-1..last] = CRC-16/Kermit of the data bytes, little-endian (only when READ_CMD or
 *                     when a vendor WRITE op needs CRC; vendor WRITE_CMD = 0x00 has no CRC)
 * SPI_HEADER_LENGTH = 4 + SPI_DUMMY_BYTE = 7.
 */
#define FOCALTECH_READ_CTRL         0xa0		/* READ_CMD = 0x80 | DATA_CRC_EN(0x20) */
#define FOCALTECH_WRITE_CTRL        0x00		/* WRITE_CMD, no CRC on TX */
#define FOCALTECH_CHIP_ID_H         0xa3
#define FOCALTECH_CHIP_ID_L         0x9f
#define FOCALTECH_TOUCH_DATA        0x01		/* the touch report lives at this address */
#define FTS_CMD_START1              0x55
#define FTS_CMD_START2              0xaa
#define FTS_CMD_START_DELAY         12		/* ms, between enter-boot and first command */
#define FTS_CMD_READ_BOOT_ID        0x90
#define FOCALTECH_MAX_TOUCHES       10
#define FOCALTECH_TOUCH_REPORT_LEN  (4 + 8 * FOCALTECH_MAX_TOUCHES)
#define FOCALTECH_MAX_TRANSFER      (7 + FOCALTECH_TOUCH_REPORT_LEN + 2)

static uint8_t focaltech_tx[FOCALTECH_MAX_TRANSFER], focaltech_rx[FOCALTECH_MAX_TRANSFER];

/* CRC-16/Kermit (polynomial 0x8408 reflected, initial 0xffff) -- same as vendor rckit_crc16(). */
static uint16_t
focaltech_crc(const uint8_t *data, uint32_t length)
{
	uint16_t crc = 0xffff;

	for (uint32_t i = 0; i < length; i++) {
		crc ^= data[i];
		for (int bit = 0; bit < 8; bit++) {
			crc = (crc & 1) ? (uint16_t)((crc >> 1) ^ 0x8408) : (uint16_t)(crc >> 1);
		}
	}
	return crc;
}

static void
log_focaltech_rx(uint8_t reg, const uint8_t *rx, uint32_t len, uint16_t exp_crc, uint16_t rec_crc)
{
	char line[96];
	uint32_t pos = 0;

	append_str(line, &pos, "focaltech: r");
	append_hex8(line, &pos, reg);
	append_str(line, &pos, " s=");
	append_hex8(line, &pos, rx[3]);
	append_str(line, &pos, " d=");
	for (uint32_t i = 7; i < len && i < 11; i++) {
		append_hex8(line, &pos, rx[i]);
		line[pos++] = ' ';
	}
	append_str(line, &pos, "crc=");
	append_hex8(line, &pos, (uint8_t)(rec_crc >> 8));
	append_hex8(line, &pos, (uint8_t)rec_crc);
	line[pos++] = '/';
	append_hex8(line, &pos, (uint8_t)(exp_crc >> 8));
	append_hex8(line, &pos, (uint8_t)exp_crc);
	line[pos++] = '\n';
	line[pos] = '\0';
	loader_log_line(line);
}

static bool
focaltech_read(uint8_t address, uint8_t *data, uint32_t length)
{
	const uint32_t data_offset = 7;
	uint32_t transfer_length = data_offset + length + 2;

	if (length == 0 || transfer_length > sizeof(focaltech_tx)) {
		return false;
	}
	for (int attempt = 0; attempt < 3; attempt++) {
		memset(focaltech_tx, 0, transfer_length);
		memset(focaltech_rx, 0, transfer_length);
		focaltech_tx[0] = address;		/* vendor: TX[0] = cmd[0] = reg address */
		focaltech_tx[1] = FOCALTECH_READ_CTRL;	/* vendor: TX[1] = ctrl = 0xA0 */
		focaltech_tx[2] = (uint8_t)(length >> 8);
		focaltech_tx[3] = (uint8_t)length;
		if (!spi_transfer(focaltech_tx, focaltech_rx, transfer_length)) {
			sleep_us(150);
			continue;
		}
		uint16_t expected = focaltech_crc(focaltech_rx + data_offset, length);
		uint16_t received = (uint16_t)(focaltech_rx[data_offset + length] |
		    focaltech_rx[data_offset + length + 1] << 8);

		if (address == FOCALTECH_CHIP_ID_H || address == FOCALTECH_CHIP_ID_L || address == FTS_CMD_READ_BOOT_ID) {
			log_focaltech_rx(address, focaltech_rx, transfer_length, expected, received);
		}

		/* vendor: bit 7 of status (rx[3]) is BUSY, bit 5 is CRC error */
		if (!(focaltech_rx[3] & 0xa0)) {
			if (expected == received) {
				memcpy(data, focaltech_rx + data_offset, length);
				sleep_us(150);		/* minimum CS-high time in the vendor driver */
				return true;
			}
		}
		sleep_us(150);
	}
	return false;
}

/*
 * Vendor fts_write: no CRC on TX. For a 1-byte "command" (length == 0) the frame is just the
 * four header bytes { addr, 0x00, 0x00, 0x00 } with no dummy and no data. For length > 0 the
 * three dummy bytes precede the data: { addr, 0x00, lenH, lenL, 0, 0, 0, data... }. The chip
 * drives the "status" byte on rx[3] -- bits 7 and 5 set mean busy or CRC error (vendor retries
 * SPI_RETRY_NUMBER = 3 times on failure before giving up).
 */
static bool
focaltech_write(uint8_t address, const uint8_t *data, uint32_t length)
{
	uint32_t transfer_length;

	if (length == 0) {
		transfer_length = 4;
	} else {
		transfer_length = 7 + length;
	}
	if (transfer_length > sizeof(focaltech_tx)) {
		return false;
	}
	memset(focaltech_tx, 0, transfer_length);
	focaltech_tx[0] = address;
	focaltech_tx[1] = FOCALTECH_WRITE_CTRL;
	focaltech_tx[2] = (uint8_t)(length >> 8);
	focaltech_tx[3] = (uint8_t)length;
	if (data && length > 0) {
		memcpy(focaltech_tx + 7, data, length);
	}
	for (int attempt = 0; attempt < 3; attempt++) {
		if (spi_transfer(focaltech_tx, focaltech_rx, transfer_length) &&
		    !(focaltech_rx[3] & 0xa0)) {
			sleep_us(150);
			return true;
		}
		sleep_us(150);
	}
	return false;
}

/*
 * Vendor fts_fwupg_get_boot_state() reads the chip's "boot ID" via the FT boot-ROM protocol:
 *   TX = { 0x55, 0xAA }                 (FTS_CMD_START1, FTS_CMD_START2 -- enter boot)
 *   wait FTS_CMD_START_DELAY = 12 ms
 *   TX = { 0x90 }, RX = 2 bytes         (FTS_CMD_READ_ID, incell cmd length)
 * If the two RX bytes are the chip's boot ID (0x56 0x62 for FT3680), firmware is present and
 * valid in flash but has not yet been started; the host must issue FTS_CMD_FIRMWARE_START
 * (0x08) to make the boot ROM jump to it.
 */
/* Boot-ROM commands for firmware (pramboot) upload, from focaltech_3658u/focaltech_flash.h. */
#define FTS_ROMBOOT_CMD_SET_PRAM_ADDR   0xad
#define FTS_ROMBOOT_CMD_WRITE           0xae
#define FTS_ROMBOOT_CMD_START_APP       0x08
#define FTS_FLASH_PACKET_LENGTH         32		/* bytes per PRAM write */

#include "hakios.focaltech_garnet_fw.h"

/*
 * Knock on the chip's boot ROM door and ask who it is. The handshake is:
 *   1. framed write { 0x55, 0xAA } -- write 0xAA to register 0x55
 *   2. delay 12 ms (FTS_CMD_START_DELAY)
 *   3. framed read of 2 bytes from register 0x90
 * For FT3683G the expected answer is { 0x56, 0x72 } (or 0x56, 0x62 for FT3680).
 */
static bool
focaltech_read_boot_id(uint8_t *high, uint8_t *low)
{
	uint8_t aa = FTS_CMD_START2;
	uint8_t out[2] = { 0 };
	bool ok;

	if (!focaltech_write(FTS_CMD_START1, &aa, 1)) {
		return false;
	}
	sleep_ms(FTS_CMD_START_DELAY);
	ok = focaltech_read(FTS_CMD_READ_BOOT_ID, out, 2);
	*high = out[0];
	*low  = out[1];
	return ok;
}

static bool
focaltech_enter_boot_rom(void)
{
	uint8_t boot_high = 0, boot_low = 0;

	for (int cnt = 0; cnt < 5; cnt++) {
		/* Hard reset pulse */
		gpio_set(PIN_RESET, false);
		sleep_ms(10);
		gpio_set(PIN_RESET, true);
		sleep_ms(FTS_CMD_START_DELAY + cnt * 10);

		if (focaltech_read_boot_id(&boot_high, &boot_low) &&
		    (boot_high == 0x56 || boot_high == 0x36) &&
		    (boot_low == 0x72 || boot_low == 0x62 || boot_low == 0x83 || boot_low == 0xb3)) {
			loader_log_line("focaltech: in boot ROM after reset\n");
			return true;
		}

		/* Also try vendor software reset { 0xFC, 0xAA } -> { 0xFC, 0x55 } */
		uint8_t aa = 0xaa, fifty_five = 0x55;
		focaltech_write(0xfc, &aa, 1);
		sleep_ms(12);
		focaltech_write(0xfc, &fifty_five, 1);
		sleep_ms(30);

		if (focaltech_read_boot_id(&boot_high, &boot_low) &&
		    (boot_high == 0x56 || boot_high == 0x36) &&
		    (boot_low == 0x72 || boot_low == 0x62 || boot_low == 0x83 || boot_low == 0xb3)) {
			loader_log_line("focaltech: in boot ROM after soft reset\n");
			return true;
		}

		char bmsg[64];
		uint32_t bpos = 0;
		append_str(bmsg, &bpos, "focaltech: boot ID attempt: ");
		append_hex8(bmsg, &bpos, boot_high);
		bmsg[bpos++] = ' ';
		append_hex8(bmsg, &bpos, boot_low);
		bmsg[bpos++] = '\n';
		bmsg[bpos] = '\0';
		loader_log_line(bmsg);
	}
	return false;
}

/* Vendor fts_wait_tp_to_valid: poll chip ID for up to TIMEOUT_READ_REG at 100 ms steps. */
static bool
focaltech_wait_valid(uint8_t *high, uint8_t *low)
{
	for (int attempt = 0; attempt < 8; attempt++) {
		if (focaltech_read(FOCALTECH_CHIP_ID_H, high, 1) &&
		    focaltech_read(FOCALTECH_CHIP_ID_L, low, 1)) {
			if ((*high == 0x56 || *high == 0x36) &&
			    (*low == 0x72 || *low == 0x62 || *low == 0x83 || *low == 0xb3)) {
				char vmsg[64];
				uint32_t vpos = 0;
				append_str(vmsg, &vpos, "focaltech: FT3683G runtime ID valid: ");
				append_hex8(vmsg, &vpos, *high);
				vmsg[vpos++] = ' ';
				append_hex8(vmsg, &vpos, *low);
				vmsg[vpos++] = '\n';
				vmsg[vpos] = '\0';
				loader_log_line(vmsg);
				return true;
			} else if (*high != 0 || *low != 0) {
				char emsg[64];
				uint32_t epos = 0;
				append_str(emsg, &epos, "focaltech: other ID read: ");
				append_hex8(emsg, &epos, *high);
				emsg[epos++] = ' ';
				append_hex8(emsg, &epos, *low);
				emsg[epos++] = '\n';
				emsg[epos] = '\0';
				loader_log_line(emsg);
			}
		}
		sleep_ms(50);
	}
	return false;
}

static bool
focaltech_write_pram(const uint8_t *buf, uint32_t len)
{
	uint8_t addr_bytes[3];

	for (uint32_t offset = 0; offset < len; offset += FTS_FLASH_PACKET_LENGTH) {
		uint32_t chunk = FTS_FLASH_PACKET_LENGTH;
		if (offset + chunk > len) {
			chunk = len - offset;
		}
		addr_bytes[0] = (uint8_t)(offset >> 16);
		addr_bytes[1] = (uint8_t)(offset >> 8);
		addr_bytes[2] = (uint8_t)offset;
		if (!focaltech_write(FTS_ROMBOOT_CMD_SET_PRAM_ADDR, addr_bytes, 3)) {
			loader_log_line("focaltech: PRAM address write failed\n");
			return false;
		}
		if (!focaltech_write(FTS_ROMBOOT_CMD_WRITE, buf + offset, chunk)) {
			loader_log_line("focaltech: PRAM data write failed\n");
			return false;
		}
	}
	return true;
}

static bool
focaltech_start_app(void)
{
	uint8_t cmd = FTS_ROMBOOT_CMD_START_APP;

	return focaltech_write(cmd, NULL, 0);
}

/*
 * Full chip bring-up: look for an already-running firmware; if none, catch boot ROM,
 * upload firmware into PRAM, start application, and verify runtime ID.
 */
static bool
focaltech_probe(bool verbose)
{
	uint8_t high = 0, low = 0;
	(void)verbose;

	/* Step 1: Maybe firmware is already running in flash / PRAM */
	if (focaltech_wait_valid(&high, &low)) {
		return true;
	}

	/* Step 2: Reset and catch the boot ROM */
	if (!focaltech_enter_boot_rom()) {
		loader_log_line("focaltech: chip not in boot ROM\n");
		return false;
	}

	/* Step 3: Upload firmware and start it */
	loader_log_line("focaltech: downloading firmware to PRAM...\n");
	if (!focaltech_write_pram(focaltech_fw, FOCALTECH_FW_LENGTH)) {
		loader_log_line("focaltech: PRAM download failed\n");
		return false;
	}
	loader_log_line("focaltech: PRAM download complete; starting application\n");
	if (!focaltech_start_app()) {
		loader_log_line("focaltech: start-app command failed\n");
		return false;
	}
	sleep_ms(300);			/* let the firmware spin up all its analog bits */

	/* Step 4: Confirm firmware is up and answering */
	if (focaltech_wait_valid(&high, &low)) {
		loader_log_line("focaltech: firmware initialized successfully\n");
		return true;
	}
	loader_log_line("focaltech: firmware did not come up after upload\n");
	return false;
}

/* ---- FocalTech touch reports --------------------------------------------------------------------- */

/*
 * Per-chip report layout for FT3680 (vendor focaltech_core.c, FTS_TOUCH_OFF_* offsets):
 *   report[0] = gesture (0 outside gesture mode)
 *   report[1] = (chip_type << 4) | finger_count
 *   report[2 + 6*i + 0] = E_XH:  bits 7..6 = event (0 = down, 1 = up, 2 = contact)
 *                                bits 3..0 = x bits 14..11
 *   report[2 + 6*i + 1] = XL:    x bits 10..3
 *   report[2 + 6*i + 2] = ID_YH: bits 7..4 = finger id, bits 3..0 = y bits 14..11
 *   report[2 + 6*i + 3] = YL:    y bits 10..3
 *   report[2 + 6*i + 4] = PRE:   bits 7..5 = x bits 2..0, bits 4..2 = y bits 2..0
 *                                (also the pressure byte -- the lowest bits of each 15-bit axis
 *                                 are packed in with it)
 *   report[2 + 6*i + 5] = AREA:  touch area / major
 * Coordinates are 15-bit "super-high resolution" sub-pixel values; the touch panel's actual
 * extent is reported through the device tree as x_max/y_max (10800 x 24000 for redwood).
 */
#define FOCALTECH_EVENT_DOWN        0
#define FOCALTECH_EVENT_UP          1
#define FOCALTECH_EVENT_CONTACT     2

static struct {
	bool down, seen;
	uint32_t x, y;
} focaltech_contact[FOCALTECH_MAX_TOUCHES];

static void
focaltech_contact_update(uint32_t id, uint32_t event, uint32_t x, uint32_t y,
    uint32_t max_report_x, uint32_t max_report_y)
{
	if (id >= FOCALTECH_MAX_TOUCHES || max_report_x == 0 || max_report_y == 0) {
		return;
	}
	if (event == FOCALTECH_EVENT_UP) {
		focaltech_contact[id].seen = true;
		if (focaltech_contact[id].down) {
			focaltech_contact[id].down = false;
			hakios_touch_post(HAKIOS_TOUCH_UP, id, focaltech_contact[id].x, focaltech_contact[id].y);
		}
		return;
	}
	seen.touches++;

	/* Clamp raw values within panel bounds */
	if (x >= max_report_x) {
		x = max_report_x - 1;
	}
	if (y >= max_report_y) {
		y = max_report_y - 1;
	}

	/* Normalize to iOS 0..65535 coordinate space */
	uint32_t norm_x = (uint32_t)(((uint64_t)x * 65535) / (max_report_x - 1));
	uint32_t norm_y = (uint32_t)(((uint64_t)y * 65535) / (max_report_y - 1));

	/* Apply axis swap if requested via boot-arg touch_swap=1 */
	if (swap_axes) {
		uint32_t tmp = norm_x;
		norm_x = norm_y;
		norm_y = tmp;
	}

	/* Apply flip: bit 0 = mirror left-right, bit 1 = mirror top-bottom */
	if (flip & 1) {
		norm_x = 65535 - norm_x;
	}
	if (flip & 2) {
		norm_y = 65535 - norm_y;
	}

	seen.last_x = norm_x;
	seen.last_y = norm_y;
	focaltech_contact[id].seen = true;
	if (!focaltech_contact[id].down) {
		focaltech_contact[id].down = true;
		hakios_touch_post(HAKIOS_TOUCH_DOWN, id, norm_x, norm_y);
		static unsigned touch_down_logs = 0;
		if (touch_down_logs < 15) {
			touch_down_logs++;
			char tmsg[64];
			uint32_t tpos = 0;
			append_str(tmsg, &tpos, "focaltech: down id=");
			append_hex8(tmsg, &tpos, (uint8_t)id);
			append_str(tmsg, &tpos, " at ");
			append_hex8(tmsg, &tpos, (uint8_t)(norm_x >> 8));
			append_hex8(tmsg, &tpos, (uint8_t)norm_x);
			tmsg[tpos++] = ' ';
			append_hex8(tmsg, &tpos, (uint8_t)(norm_y >> 8));
			append_hex8(tmsg, &tpos, (uint8_t)norm_y);
			tmsg[tpos++] = '\n';
			tmsg[tpos] = '\0';
			loader_log_line(tmsg);
		}
	} else if (focaltech_contact[id].x != norm_x || focaltech_contact[id].y != norm_y) {
		hakios_touch_post(HAKIOS_TOUCH_MOVE, id, norm_x, norm_y);
	}
	focaltech_contact[id].x = norm_x;
	focaltech_contact[id].y = norm_y;
}

/* Panel size in the FT3683G super-high-resolution reports (device tree display-coords on Garnet). */
static uint32_t focaltech_max_x = 19520, focaltech_max_y = 43392;

static void
focaltech_report(const uint8_t *report)
{
	uint8_t format = (report[1] >> 4) & 0x0f;
	uint8_t count = report[1] & 0x0f;

	for (uint32_t i = 0; i < FOCALTECH_MAX_TOUCHES; i++) {
		focaltech_contact[i].seen = false;
	}

	if (format == 2) {
		/* Protocol Version 2 (PV2, super-resolution): 8 bytes per touch, starting at report + 4 */
		for (uint32_t i = 0; i < count && i < FOCALTECH_MAX_TOUCHES; i++) {
			const uint8_t *touch = report + 4 + 8 * i;
			uint32_t id = (touch[2] >> 4) & 0x0f;
			if (id >= FOCALTECH_MAX_TOUCHES) {
				continue;
			}
			uint32_t event = (touch[0] >> 6) & 0x03;
			uint32_t x = ((uint32_t)(touch[0] & 0x0f) << 12) |
			             ((uint32_t)touch[1] << 4) |
			             ((uint32_t)touch[4] >> 4);
			uint32_t y = ((uint32_t)(touch[2] & 0x0f) << 12) |
			             ((uint32_t)touch[3] << 4) |
			             ((uint32_t)touch[4] & 0x0f);
			focaltech_contact_update(id, event, x, y, focaltech_max_x, focaltech_max_y);
		}
	} else {
		/* Standard FocalTech protocol: 6 bytes per touch, starting at report + 2 */
		for (uint32_t i = 0; i < count && i < FOCALTECH_MAX_TOUCHES; i++) {
			const uint8_t *touch = report + 2 + 6 * i;
			uint32_t id = (touch[2] >> 4) & 0x0f;
			if (id >= FOCALTECH_MAX_TOUCHES) {
				continue;
			}
			uint32_t event = (touch[0] >> 6) & 0x03;
			uint32_t x = ((uint32_t)(touch[0] & 0x0f) << 8) | (uint32_t)touch[1];
			uint32_t y = ((uint32_t)(touch[2] & 0x0f) << 8) | (uint32_t)touch[3];
			focaltech_contact_update(id, event, x, y, 1220, 2712);
		}
	}

	/* Fingers not in this report are up (vendor driver uses a bitmap; we remember explicitly). */
	for (uint32_t i = 0; i < FOCALTECH_MAX_TOUCHES; i++) {
		if (!focaltech_contact[i].seen && focaltech_contact[i].down) {
			focaltech_contact[i].down = false;
			hakios_touch_post(HAKIOS_TOUCH_UP, i, focaltech_contact[i].x, focaltech_contact[i].y);
		}
	}
}

static void
focaltech_poll(void)
{
	static uint8_t report[FOCALTECH_TOUCH_REPORT_LEN];
	static unsigned bad;

	seen.polls++;
	if (!focaltech_read(FOCALTECH_TOUCH_DATA, report, sizeof(report))) {
		seen.bad++;
		if (bad++ < 8) {
			loader_log_line("focaltech: SPI read failed for touch report\n");
		}
		return;
	}
	seen.reports++;
	focaltech_report(report);
}

#include "hakios.novatek_ruan.h"

/* Which touch chip is on this board. */
enum touch_chip { TOUCH_GOODIX, TOUCH_FOCALTECH, TOUCH_NOVATEK };
static enum touch_chip touch_chip;
static uint32_t ruan_touch;     /* boot-arg ruan_touch=1: Redmi Pad Pro 5G, NT36532 (hakios.novatek_ruan.h) */

static enum touch_chip
touch_chip_detect(void)
{
	return ruan_touch ? TOUCH_NOVATEK : TOUCH_FOCALTECH;
}

static bool
chip_probe(bool verbose)
{
	if (touch_chip == TOUCH_NOVATEK) {
		return novatek_probe(verbose);
	}
	if (touch_chip == TOUCH_FOCALTECH) {
		return focaltech_probe(verbose);
	}
	touch_reset();
	return goodix_probe(verbose);
}

static void
chip_poll(void)
{
	if (touch_chip == TOUCH_NOVATEK) {
		novatek_poll();
	} else if (touch_chip == TOUCH_FOCALTECH) {
		focaltech_poll();
	} else {
		goodix_poll();
	}
}

/* ---- all of it together ---------------------------------------------------------------------------- */

static void
show_state(const char *when)
{
	(void)when;
}

/* Power the chip up, in the vendor driver's order. */
static void
power_on(void)
{
	loader_log_line("focaltech: power_on start\n");
	if (touch_chip == TOUCH_NOVATEK) {
		/* ruan: TDDI, powered and reset with the panel; only the report line is ours */
		gpio_configure(NVT_PIN_INT, 0, PULL_UP, 2, false);
		nvt_edge_latch_on();
		sleep_ms(10);
		return;
	}
	gpio_output(PIN_RESET, false, PULL_UP, 8);
	gpio_configure(PIN_INT, 0, PULL_UP, 8, false);
	io_supply_on();
	sleep_ms(20);
	gpio_set(PIN_RESET, true);
	sleep_ms(100);
	loader_log_line("focaltech: power_on complete\n");
}

static void
use_engine_pins(void)
{
	gpio_configure(PIN_MISO, PIN_FUNCTION_SPI, PULL_NONE, 6, false);
	gpio_configure(PIN_MOSI, PIN_FUNCTION_SPI, PULL_NONE, 4, true);
	gpio_configure(PIN_CLK, PIN_FUNCTION_SPI, PULL_NONE, 4, true);
	gpio_configure(PIN_CS, PIN_FUNCTION_SPI, PULL_NONE, 6, true);
}

static const char *
chip_name(void)
{
	return touch_chip == TOUCH_NOVATEK ? "novatek" : touch_chip == TOUCH_FOCALTECH ? "focaltech" : "goodix";
}

static bool
bring_up(void)
{
	const char *why = NULL;

	touch_chip = touch_chip_detect();
	power_on();

	/* Try hardware GENI SPI first */
	if (se && gcc && clocks_on()) {
		why = geni_spi_init(6000000);
		if (!why) {
			use_engine_pins();
			loader_log_line("focaltech: serial engine initialized, probing...\n");
			spi_transfer = geni_transfer;
			if (chip_probe(true)) {
				loader_log_line("focaltech: chip answers through serial engine!\n");
				return true;
			}
			loader_log_line("focaltech: no answer through serial engine\n");
		} else {
			loader_log_line("focaltech: cannot use serial engine: ");
			loader_log_line(why);
			loader_log_line("\n");
		}
	} else {
		loader_log_line("focaltech: se/gcc not ready or clocks_on failed\n");
	}

	/* Fall back to bitbang */
	loader_log_line("focaltech: falling back to bitbang\n");
	spi_transfer = bitbang_transfer;
	for (int attempt = 0; attempt < 2; attempt++) {
		bitbang_in = attempt == 0 ? PIN_MISO : PIN_MOSI;
		bitbang_out = attempt == 0 ? PIN_MOSI : PIN_MISO;
		bitbang_init();
		if (touch_chip == TOUCH_NOVATEK) {
			spi_transfer = bitbang_fast_transfer;
		}
		if (chip_probe(attempt == 0)) {
			loader_log_line("focaltech: chip answers on pins driven by hand\n");
			return true;
		}
	}
	loader_log_line("focaltech: no answer from touch chip\n");
	return false;
}

static uint64_t
micros_now(void)
{
	uint64_t ns;

	absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
	return ns / 1000;
}

static void
goodix_thread(__unused void *parameter, __unused wait_result_t result)
{

	unsigned idle = 0, idle_looks;
	uint32_t poll_us = 8000, reads = 0;
	uint64_t before = 0, reading = 0;

	PE_parse_boot_argn("touch_poll_us", &poll_us, sizeof(poll_us));
	if (poll_us < 250 || poll_us > 100000) {
		poll_us = 8000;
	}
	idle_looks = 80000 / poll_us;   /* a report read every 80 ms even with the line high, in case it is missed */

	loader_log_line("focaltech: thread running, mapping tlmm\n");
	tlmm = ml_io_map(TLMM_PHYS, TLMM_SIZE);
	if (!tlmm) {
		loader_log_line("focaltech: failed to map tlmm\n");
		thread_terminate(current_thread());
		return;
	}
	loader_log_line("focaltech: tlmm mapped successfully\n");
	gcc = ml_io_map(GCC_PHYS, GCC_SIZE);
	se = ml_io_map(SE_PHYS, SE_SIZE);
	rsc = ml_io_map(RSC_PHYS, RSC_SIZE);
	cmd_db = ml_io_map_wcomb(CMD_DB_PHYS, CMD_DB_SIZE);
	if (!rsc) {
		loader_log_line("focaltech: failed to map rsc\n");
	}
	if (!cmd_db) {
		loader_log_line("focaltech: failed to map cmd_db\n");
	}

	if (!bring_up()) {
		loader_log_line("focaltech: no touch screen detected\n");
		thread_terminate(current_thread());
		return;
	}
	loader_log_line("focaltech: touch screen ready\n");
	{
		uint32_t rate = 0;

		/* boot-arg touch_rate=480: the chip reports twice as often (Xiaomi's game mode; 240 otherwise) */
		if (PE_parse_boot_argn("touch_rate", &rate, sizeof(rate)) && rate == 480 && touch_chip == TOUCH_GOODIX) {
			goodix_command(GOODIX_CMD_HIGH_RATE, 1);
		}
	}
	for (unsigned tick = 1;; tick++) {
		uint64_t looked = micros_now(), read_at;

		/* the interrupt line is low while a report waits; look anyway every 80 ms in case it is missed */
		if (touch_chip == TOUCH_NOVATEK ? nvt_edge_seen() : !gpio_get(PIN_INT)) {
			idle = 0;
			chip_poll();
			read_at = micros_now();
			reads++;
			reading += read_at - looked;
		} else if (++idle >= idle_looks) {
			idle = 0;
			chip_poll();
			reads++;
			reading += micros_now() - looked;
		}
		before = looked;
		sleep_us(poll_us);
	}
}

void
hakios_focaltech_init(void)
{
	uint32_t enabled = 0;
	thread_t thread;

	PE_parse_boot_argn("ruan_touch", &ruan_touch, sizeof(ruan_touch));
	if (ruan_touch) {
		enabled = 1;
	} else if (!PE_parse_boot_argn("touchscreen", &enabled, sizeof(enabled)) &&
	    !PE_parse_boot_argn("garnet_touch", &enabled, sizeof(enabled))) {
		return;
	}
	if (!enabled) {
		return;
	}
	PE_parse_boot_argn("touch_flip", &flip, sizeof(flip));
	PE_parse_boot_argn("touch_swap", &swap_axes, sizeof(swap_axes));
	if (kernel_thread_start(goodix_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	}
}
