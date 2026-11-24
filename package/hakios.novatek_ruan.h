/*
 * Redmi Pad Pro 5G (ruan, SM7435): Novatek NT36532 touch (TDDI, no flash) on the same QUP SE at 0xa8c000 and
 * the same SPI pins (gpio10-13) as garnet's FocalTech; included by hakios.focaltech.c, which owns the bus.
 * Boot-arg ruan_touch=1. The chip has no reset pin of its own (the panel's) and no supply of its own to vote.
 *
 * The NT36532 bus protocol and host download below are a port of NvtProtocol.c from
 * github.com/iOSNJBrepo/macOS-uke (touch/src/drivers/NativeNovatekTouch, Apache License 2.0; its NOTICE: the bus
 * facts come from reading Novatek's Linux nt36532e driver, no code copied). Point records: the classic NT36xxx
 * layout of ruan's own vendor driver (nt36532_spi.ko: "point_data" with a checksum, no THP).
 */
#include "hakios.novatek_ruan_fw.h"     /* novatek_ruan_fw[]: /vendor/firmware/novatek_ts_fw_boe.bin (not in git) */

/* The live DT has novatek,irq-gpio = <&tlmm 0x36 0x2001> and interrupts = <0x36 2> (falling edge): 0x36 is GPIO 54, not 36.
 * touch_fast=1 (RuanTouch.c) switches to 54; 36 stays the default until a boot confirms 54's edges. */
static unsigned nvt_pin_int = 36;
#define NVT_PIN_INT             nvt_pin_int
#define NVT_EVENT_BUF           0x125800 /* NT36532 (single chip / cascade); NT36532E is 0x11C400 */
#define NVT_BOOT_RDY            0x1FB50D
#define NVT_TX_AUTO_COPY_EN     0x1FC925
#define NVT_ILM_DES             0x1FB528
#define NVT_ILM_LENGTH          0x1FB518
#define NVT_DLM_DES             0x1FB52C
#define NVT_DLM_LENGTH          0x1FB530
#define NVT_G_ILM_CHECKSUM      0x1FB500
#define NVT_G_DLM_CHECKSUM      0x1FB504
#define NVT_CHIP_VER_TRIM       0x1FB104
#define NVT_SWRST_SIF           0x1FB43E
#define NVT_ENG_RST             0x7FFF80
#define NVT_EV_HOST_CMD         0x50
#define NVT_EV_RESET_COMPLETE   0x60
#define NVT_EV_FWINFO           0x78
#define NVT_CHUNK               1024    /* bytes per SPI write; geni_transfer's deadline is 200 ms */
#define NVT_MAX_PARTS           64
#define NVT_POINTS              10

static uint8_t nvt_tx[NVT_CHUNK + 8], nvt_rx[NVT_CHUNK + 8];

/* The report line is a pulse (edge IRQ): let the TLMM latch it. INTR_CFG at +8, INTR_STATUS at +0xc of the pin's
 * block (pinctrl-msm: enable bit 0, polarity bit 1, detection bits 2-3, raw status bit 4). Delivery stays off (bit 0):
 * the status bit latches with raw status on, and the touch thread reads it instead of an interrupt. */
#define NVT_INTR_CFG            (tlmm + 0x1000UL * NVT_PIN_INT + 8)
#define NVT_INTR_STATUS         (tlmm + 0x1000UL * NVT_PIN_INT + 0xc)

static void
nvt_edge_latch_on(void)
{
	uint32_t cfg = rd(NVT_INTR_CFG) & ~0x1fu;
	wr(NVT_INTR_CFG, cfg | (1u << 4) | (3u << 2) | (1u << 1));   /* raw status, both edges, active high */
	wr(NVT_INTR_STATUS, 0);
}

static bool
nvt_edge_seen(void)
{
	if (rd(NVT_INTR_STATUS) & 1) {
		wr(NVT_INTR_STATUS, 0);
		return true;
	}
	return false;
}

/* touch_irq=1: a real interrupt. All TLMM pins share the summary line, SPI 208 level high (pinctrl@f000000 interrupts =
 * <0 0xd0 4>), INTID 240. Linux on ruan takes GPIO 54 through the PDC instead (parrot_pdc_map {54, 94} -> SPI 609), but
 * the summary path is the one sheng's TouchProbe.cpp uses with ArmCpu's armcpu_spi_share, and needs no PDC writes.
 * INTR_CFG (pinctrl-parrot.h PINGROUP): enable 0, polarity 1, detection 3:2, raw status 4, target 7:5 (3 = apps).
 * Rising edge, as ruan's vendor driver requests it (nt36xxx.h INT_TRIGGER_TYPE), whatever the DT cell says. */
extern int armcpu_spi_share(uint32_t, void (*)(void *), void *) __attribute__((weak_import));
extern kern_return_t clear_wait(thread_t thread, wait_result_t result);
extern kern_return_t thread_wakeup_prim(event_t event, boolean_t one_thread, wait_result_t result);
#define NVT_TLMM_SUMMARY_INTID  (32 + 208)

static volatile uint32_t nvt_irq_events, nvt_irq_spurious;
static volatile uint64_t nvt_irq_at;    /* mach_absolute_time of the last interrupt, for the latency numbers */

static void
nvt_irq(__unused void *context)
{
	if (!(rd(NVT_INTR_STATUS) & 1)) {
		nvt_irq_spurious = nvt_irq_spurious + 1;       /* another pin's summary interrupt */
		return;
	}
	wr(NVT_INTR_STATUS, 0);
	nvt_irq_at = mach_absolute_time();
	__atomic_fetch_add(&nvt_irq_events, 1, __ATOMIC_RELEASE);
	thread_wakeup_prim((event_t)&nvt_irq_events, FALSE, THREAD_AWAKENED);
}

/* Returns 0 once the line is attached; else the attach result (retried by the caller: the GIC may not be up yet). */
static int
nvt_irq_arm(void)
{
	if (!armcpu_spi_share) {
		return -1;
	}
	uint32_t cfg = rd(NVT_INTR_CFG) & ~0xffu;
	cfg |= (3u << 5) | (1u << 4) | (1u << 2) | (1u << 1);  /* apps, raw status, rising edge, polarity high; enable last */
	wr(NVT_INTR_CFG, cfg);
	wr(NVT_INTR_STATUS, 0);
	__asm__ volatile ("dsb sy" ::: "memory");
	int rc = armcpu_spi_share(NVT_TLMM_SUMMARY_INTID, nvt_irq, NULL);
	if (rc == 0) {
		wr(NVT_INTR_CFG, cfg | 1u);
	}
	return rc;
}

/* Sleeps until an interrupt newer than `seen`, or `ms` pass. */
static void
nvt_irq_wait(uint32_t seen, uint32_t ms)
{
	uint64_t deadline;

	clock_interval_to_deadline(ms, NSEC_PER_MSEC, &deadline);
	assert_wait_deadline_with_leeway((event_t)&nvt_irq_events, THREAD_UNINT, TIMEOUT_URGENCY_SYS_CRITICAL, deadline, 0);
	if (__atomic_load_n(&nvt_irq_events, __ATOMIC_ACQUIRE) != seen) {
		clear_wait(current_thread(), THREAD_AWAKENED);  /* it came between the caller's look and the assert */
		return;
	}
	thread_block(THREAD_CONTINUE_NULL);
}
static uint16_t nvt_max_x = 1600, nvt_max_y = 2560;

static void
nvt_log(const char *what, uint32_t a, uint32_t b)
{
	char m[96];
	uint32_t p = 0;
	append_str(m, &p, "novatek: ");
	append_str(m, &p, what);
	m[p++] = ' ';
	append_hex32(m, &p, a);
	m[p++] = ' ';
	append_hex32(m, &p, b);
	m[p++] = '\n';
	m[p] = 0;
	loader_log_line(m);
}

static bool
nvt_bus_write(uint32_t len)             /* nvt_tx[0..len) = [offset, data...] */
{
	nvt_tx[0] |= 0x80;
	return spi_transfer(nvt_tx, nvt_rx, len);
}

static bool
nvt_set_page(uint32_t addr)
{
	nvt_tx[0] = 0xff;
	nvt_tx[1] = (uint8_t)(addr >> 15);
	nvt_tx[2] = (uint8_t)(addr >> 7);
	return nvt_bus_write(3);
}

static bool
nvt_write(uint32_t addr, const uint8_t *data, uint32_t len)
{
	if (len == 0 || len > NVT_CHUNK || !nvt_set_page(addr)) {
		return false;
	}
	nvt_tx[0] = (uint8_t)(addr & 0x7f);
	memcpy(nvt_tx + 1, data, len);
	return nvt_bus_write(len + 1);
}

static bool
nvt_write_byte(uint32_t addr, uint8_t v)
{
	return nvt_write(addr, &v, 1);
}

static bool
nvt_write_le(uint32_t addr, uint32_t v, uint32_t n)
{
	uint8_t b[4] = { (uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24) };
	return nvt_write(addr, b, n);
}

/* reads: tx = [offset, dummy...], the data starts at rx[2] */
static bool
nvt_read(uint32_t addr, uint8_t *out, uint32_t len)
{
	if (len == 0 || len > NVT_CHUNK || !nvt_set_page(addr)) {
		return false;
	}
	memset(nvt_tx, 0, len + 2);
	nvt_tx[0] = (uint8_t)(addr & 0x7f);
	if (!spi_transfer(nvt_tx, nvt_rx, len + 2)) {
		return false;
	}
	memcpy(out, nvt_rx + 2, len);
	return true;
}

static bool
nvt_read_same_page(uint32_t addr, uint8_t *out, uint32_t len)
{
	memset(nvt_tx, 0, len + 2);
	nvt_tx[0] = (uint8_t)(addr & 0x7f);
	if (!spi_transfer(nvt_tx, nvt_rx, len + 2)) {
		return false;
	}
	memcpy(out, nvt_rx + 2, len);
	return true;
}

/* ---- firmware image (the vendor's partition table) ---- */

struct nvt_part { uint32_t bin, sram, size, crc; };
static struct nvt_part nvt_parts[NVT_MAX_PARTS];
static unsigned nvt_nparts;
static bool nvt_cascade_hdr;

static uint32_t
nvt_le32(const uint8_t *d)
{
	return (uint32_t)d[0] | ((uint32_t)d[1] << 8) | ((uint32_t)d[2] << 16) | ((uint32_t)d[3] << 24);
}

static uint32_t
nvt_crc32(const uint8_t *data, uint32_t len, uint32_t avail)
{
	uint32_t c = 0xffffffffu, words = (len + 4) / 4;
	for (uint32_t i = 0; i < words; i++) {
		uint32_t w = 0;
		for (unsigned b = 0; b < 4; b++) {
			if (i * 4 + b < avail) {
				w |= (uint32_t)data[i * 4 + b] << (8 * b);
			}
		}
		c ^= w;
		for (unsigned j = 0; j < 32; j++) {
			c = (c & 0x80000000u) ? (c << 1) ^ 0x04c11db7u : (c << 1);
		}
	}
	return c;
}

static bool
nvt_fw_parse(const uint8_t *d, uint32_t size)
{
	if (size < 0x40) {
		return false;
	}
	uint32_t end = nvt_le32(d), pos = 0x30;
	if (end < 0x30 || end > size) {
		return false;
	}
	nvt_cascade_hdr = (d[0x20] & 0x02) != 0;
	unsigned info = 0;
	if (nvt_cascade_hdr) {
		while (pos < end / 2) { info++; pos += 0x10; }
		info++;
	} else {
		while (pos < end) { info++; pos += 0x10; }
	}
	unsigned ovly = (d[0x28] & 0x10) ? (d[0x28] & 0x0f) : 0;
	nvt_nparts = 2 + ovly + info;
	if (nvt_nparts > NVT_MAX_PARTS) {
		return false;
	}
	bool header = false;
	for (unsigned i = 0; i < nvt_nparts; i++) {
		struct nvt_part *p = &nvt_parts[i];
		if (i < 2) {                                    /* ILM, DLM */
			p->bin = nvt_le32(d + i * 12);
			p->sram = nvt_le32(d + 4 + i * 12);
			p->size = nvt_le32(d + 8 + i * 12);
			if ((uint64_t)p->bin + p->size > size) {
				return false;
			}
			p->crc = nvt_crc32(d + p->bin, p->size, size - p->bin);
			continue;
		}
		if (i < 2 + info) {                             /* info sections and the bin header */
			if (!header) {
				pos = 0x30 + 0x10 * (i - 2);
			} else if (nvt_cascade_hdr) {
				pos = end - 0x10;
			}
		} else {                                        /* overlays */
			pos = nvt_parts[1].bin + 0x10 * (i - 2 - info);
		}
		if ((uint64_t)pos + 16 > size) {
			return false;
		}
		p->sram = nvt_le32(d + pos);
		p->size = nvt_le32(d + pos + 4);
		p->bin = nvt_le32(d + pos + 8);
		p->crc = nvt_le32(d + pos + 12);
		if (i < 2 + info && p->bin < end && p->size) {
			header = true;
		}
		if ((uint64_t)p->bin + p->size > size) {
			return false;
		}
	}
	return true;
}

/* ---- identify, download, start ---- */

static bool
nvt_bootloader_reset(void)
{
	bool ok = nvt_write_byte(NVT_SWRST_SIF, 0x69);
	sleep_ms(5);
	return ok;
}

static bool
nvt_identify(void)
{
	uint8_t id[6] = { 0 };
	if (!nvt_write_byte(NVT_ENG_RST, 0x5a)) {
		return false;
	}
	sleep_ms(11);
	for (int retry = 0; retry < 5; retry++) {
		if (!nvt_bootloader_reset() || !nvt_set_page(NVT_CHIP_VER_TRIM)) {
			return false;
		}
		memset(nvt_tx, 0, 7);
		nvt_tx[0] = NVT_CHIP_VER_TRIM & 0x7f;
		if (!nvt_bus_write(7) || !nvt_read(NVT_CHIP_VER_TRIM, id, 6)) {
			return false;
		}
		nvt_log("trim id", nvt_le32(id), (uint32_t)id[4] | ((uint32_t)id[5] << 8));
		if (id[3] == 0x32 && id[4] == 0x65 && id[5] == 0x03) {
			return true;
		}
		sleep_ms(10);
	}
	return false;
}

static bool
nvt_download(void)
{
	const uint8_t *fw = novatek_ruan_fw;
	uint32_t fw_size = NOVATEK_RUAN_FW_LENGTH;

	for (int attempt = 1; attempt <= 3; attempt++) {
		unsigned stage = 1;
		uint8_t st[5] = { 0 }, zero[7] = { 0 };
		if (!nvt_bootloader_reset()) goto fail;
		stage = 2;
		if (!nvt_write_le(NVT_ILM_DES, nvt_parts[0].sram, 3) || !nvt_write_le(NVT_ILM_LENGTH, nvt_parts[0].size, 3) ||
		    !nvt_write_le(NVT_G_ILM_CHECKSUM, nvt_parts[0].crc, 4) || !nvt_write_le(NVT_DLM_DES, nvt_parts[1].sram, 3) ||
		    !nvt_write_le(NVT_DLM_LENGTH, nvt_parts[1].size, 3) || !nvt_write_le(NVT_G_DLM_CHECKSUM, nvt_parts[1].crc, 4)) goto fail;
		if (nvt_cascade_hdr) {
			stage = 3;
			if (!nvt_write_byte(NVT_TX_AUTO_COPY_EN, 0x56)) goto fail;
		}
		stage = 4;
		for (unsigned i = 0; i < nvt_nparts; i++) {
			struct nvt_part *p = &nvt_parts[i];
			/* the vendor writes size+1 bytes per partition when the image has them */
			uint32_t left = p->size ? ((uint64_t)p->bin + p->size + 1 <= fw_size ? p->size + 1 : p->size) : 0;
			uint32_t sram = p->sram, bin = p->bin;
			while (left) {
				uint32_t n = left < NVT_CHUNK ? left : NVT_CHUNK;
				if (!nvt_write(sram, fw + bin, n)) goto fail;
				sram += n; bin += n; left -= n;
			}
		}
		if (nvt_cascade_hdr) {
			stage = 5;
			uint8_t v = 0xff;
			for (int i = 0; i < 200 && v; i++) {
				if (!nvt_read(NVT_TX_AUTO_COPY_EN, &v, 1)) goto fail;
				if (v) sleep_ms(1);
			}
			if (v) goto fail;
		}
		stage = 6;
		if (!nvt_write(NVT_EVENT_BUF + NVT_EV_RESET_COMPLETE, zero, sizeof zero) ||
		    !nvt_write_byte(NVT_EVENT_BUF + NVT_EV_HOST_CMD, 0xae)) goto fail;
		stage = 7;
		if (!nvt_write_byte(NVT_BOOT_RDY, 1)) goto fail;
		sleep_ms(5);
		stage = 8;
		for (int retry = 0; retry <= 10; retry++) {
			if (!nvt_read(NVT_EVENT_BUF + NVT_EV_RESET_COMPLETE, st, 5)) goto fail;
			if (st[0] >= 0xa0 && st[0] <= 0xaf) {
				nvt_log("firmware running, reset state", st[0], attempt);
				return true;
			}
			sleep_ms(10);
		}
fail:
		nvt_log("download failed at stage, attempt", stage, attempt);
	}
	return false;
}

static bool
nvt_fw_info(void)
{
	uint8_t b[38];
	for (int attempt = 0; attempt < 4; attempt++) {
		if (!nvt_read(NVT_EVENT_BUF + NVT_EV_FWINFO, b, sizeof b)) {
			return false;
		}
		if ((uint8_t)(b[0] + b[1]) == 0xff) {
			uint16_t mx = (uint16_t)((b[4] << 8) | b[5]), my = (uint16_t)((b[6] << 8) | b[7]);
			if (mx > 1 && my > 1) {
				nvt_max_x = mx;
				nvt_max_y = my;
			}
			nvt_log("fw ver/x_num,y_num", b[0], ((uint32_t)b[2] << 8) | b[3]);
			nvt_log("abs max x, y", nvt_max_x, nvt_max_y);
			ruan_touch_max_x = nvt_max_x, ruan_touch_max_y = nvt_max_y;
			return true;
		}
		sleep_ms(10);
	}
	nvt_log("no firmware info; keeping max x, y", nvt_max_x, nvt_max_y);
	return false;
}

static bool
novatek_probe(bool verbose)
{
	(void)verbose;
	if (!nvt_identify()) {
		loader_log_line("novatek: no NT36532 trim id\n");
		return false;
	}
	if (!nvt_fw_parse(novatek_ruan_fw, NOVATEK_RUAN_FW_LENGTH)) {
		loader_log_line("novatek: firmware image does not parse\n");
		return false;
	}
	nvt_log("firmware partitions, cascade header", nvt_nparts, nvt_cascade_hdr);
	if (!nvt_download()) {
		return false;
	}
	sleep_ms(50);
	(void)nvt_fw_info();
	return true;
}

/* touch_active=1: Xiaomi's Touch_Active_MODE (ruan nt36xxx.c nvt_set_cur_value -> nvt_xiaomi_write_reg(0x7A, 1)): the
 * bytes 0x7A, 0x01 at EVENT_BUF + 0x50. The vendor sends it only while a game asks; it is lost on a firmware reload. */
static bool nvt_active;

static void
nvt_send_active(void)
{
	static const uint8_t cmd[2] = { 0x7a, 0x01 };

	if (nvt_active) {
		nvt_log("active mode write ok, ", nvt_write(NVT_EVENT_BUF + NVT_EV_HOST_CMD, cmd, sizeof cmd), 0);
	}
}

/* ---- points ---- */

static void
novatek_poll(void)
{
	static unsigned bad_reads, bad_sums, shown, polls, valid;
	uint8_t pd[66];
	bool active[NVT_POINTS] = { false };

	/* The report line is an edge (irq-gpio flags 0x2001): too short to catch by polling its level, so read the
	 * points every poll and keep what passes the checksum. */
	static bool page_set;
	static unsigned fd_run, recoveries;
	polls++;
	if (!page_set) {
		page_set = nvt_set_page(NVT_EVENT_BUF);
	}
	if (!page_set || !nvt_read_same_page(NVT_EVENT_BUF, pd, 65)) {
		page_set = false;
		if (bad_reads++ < 8) loader_log_line("novatek: point read failed\n");
		return;
	}
	bool wdt = true;
	for (int i = 0; i < 6; i++) {
		if (pd[i] != 0xfd && pd[i] != 0xfe) { wdt = false; break; }
	}
	if (!wdt) {
		fd_run = 0;
	} else if (++fd_run > 10) {
		fd_run = 0;
		page_set = false;
		if (recoveries < 1000) {
			recoveries++;
			nvt_log("firmware reset itself (0xFD): recovery#, at poll", recoveries, polls);
			if (nvt_download()) {
				sleep_ms(50);
				nvt_send_active();
			}
		}
		return;
	}
	/* the vendor driver's check: the low byte of the sum of pd[0..63] plus pd[64] is zero */
	uint8_t sum = 0;
	for (int i = 0; i < 64; i++) sum += pd[i];
	/* diagnostics: the buffer as it is (finger or not) every 256 polls for the first 32, and the run state */
	if ((polls & 0xff) == 1 && polls < 0x2000) {
		uint8_t st[2] = { 0 };
		(void)nvt_read(NVT_EVENT_BUF + NVT_EV_RESET_COMPLETE, st, 2);
		page_set = false;
		nvt_log("poll#, run state", polls, ((uint32_t)st[0] << 8) | st[1]);
		nvt_log("buf 0-3, 4-7", nvt_le32(pd), nvt_le32(pd + 4));
		nvt_log("buf 8-11, sum|chk", nvt_le32(pd + 8), ((uint32_t)sum << 8) | pd[64]);
		nvt_log("sum fails, valid", bad_sums, valid);
	}
	bool any = false;
	for (int i = 0; i < NVT_POINTS; i++) {
		unsigned id = pd[6 * i] >> 3;
		if (id && id <= NVT_POINTS) any = true;
	}
	if (any && shown < 6) {                 /* the first packets with a finger in them, raw, to check the layout */
		shown++;
		nvt_log("raw 0-3, 4-7", nvt_le32(pd), nvt_le32(pd + 4));
		nvt_log("raw 8-11, sum+chk", nvt_le32(pd + 8), ((uint32_t)sum << 8) | pd[64]);
	}
	if ((uint8_t)(sum + pd[64]) != 0) {
		bad_sums++;
		return;
	}
	valid++;
	if ((polls & 0x3ff) == 0) nvt_log("polls, valid packets", polls, valid);
	for (int i = 0; i < NVT_POINTS; i++) {
		const uint8_t *r = pd + 6 * i;
		unsigned id = r[0] >> 3, status = r[0] & 0x07;
		if (id == 0 || id > NVT_POINTS) {
			continue;
		}
		if (status == 1 || status == 2) {               /* finger down / moving */
			/* Xiaomi's "super resolution" firmware: 16-bit coordinates, ten times the panel (fw info 16000 x 25600),
			 * not the classic 12-bit packing (x = r1<<4 | r3>>4). Checked on raw packets: 16-bit stays in range. */
			uint32_t x = ((uint32_t)r[1] << 8) | r[2];
			uint32_t y = ((uint32_t)r[3] << 8) | r[4];
			ruan_touch_raw_x = x;                   /* ruan: the raw coordinates, for the boot-progress banner */
			ruan_touch_raw_y = y;
			active[id - 1] = true;
			focaltech_contact_update(id - 1, 0, x, y, nvt_max_x, nvt_max_y);
		}
	}
	{	/* ruan: multi-finger reports (USB `touch`): a phantom second contact turns the iPadOS keyboard into a trackpad */
		extern volatile uint32_t ruan_touch_multi, ruan_touch_maxfingers, ruan_touch_lastmulti[4];
		uint32_t n = 0, ids = 0;
		for (int i = 0; i < NVT_POINTS; i++) if (active[i]) {n++; ids |= 1u << i;}
		if (n > ruan_touch_maxfingers) ruan_touch_maxfingers = n;
		if (n >= 2) {
			ruan_touch_multi++;
			ruan_touch_lastmulti[0] = ids;
			unsigned k = 1;
			for (int i = 0; i < NVT_POINTS && k < 4; i++) if (active[i]) ruan_touch_lastmulti[k++] = (focaltech_contact[i].x << 16) | (focaltech_contact[i].y & 0xffff);
		}
	}
	for (int i = 0; i < NVT_POINTS; i++) {
		if (!active[i] && focaltech_contact[i].down) {
			focaltech_contact[i].down = false;
			hakios_touch_post(HAKIOS_TOUCH_UP, i, focaltech_contact[i].x, focaltech_contact[i].y);
		}
	}
}
