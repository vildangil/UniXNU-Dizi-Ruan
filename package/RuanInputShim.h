/* ruan: what HakiOS's sys/hakios.input.h gave its touch and button drivers (RuanTouch.c, RuanButtons.c); RuanInput.c implements it. */
#pragma once
#include <stdint.h>
#define HAKIOS_TOUCH_DOWN 1
#define HAKIOS_TOUCH_MOVE 2
#define HAKIOS_TOUCH_UP 3
#define HAKIOS_BUTTON_DOWN 4
#define HAKIOS_BUTTON_UP 5
#define HAKIOS_BUTTON_LOCK 1
#define HAKIOS_BUTTON_VOLUME_UP 2
#define HAKIOS_BUTTON_VOLUME_DOWN 3
#define HAKIOS_BUTTON_HOME 4
/* x, y: 0 = left/top edge, 65535 = right/bottom edge of the display. */
void hakios_touch_post(uint32_t type, uint32_t finger, uint32_t x, uint32_t y);
void hakios_focaltech_init(void);
void hakios_buttons_init(void);
void hakios_spmi_lock(void);
void hakios_spmi_unlock(void);
/* RuanButtons.c (garnet: writes PM6150L GPIO3, which on ruan is the panel supply). Only RuanTouch.c's garnet power path calls it,
 * and ruan's NT36532 returns before that (powered with the panel). */
#include <stdbool.h>
bool garnet_enable_touch_vddio(void);
/* ruan diagnostics (RuanInput.c), shown on the boot-progress banner: the NT36532's raw last point and its fw-info axis maxima. */
/* hardware presses seen by RuanButtons.c, by HAKIOS_BUTTON_* - 1: power, volume up, volume down (USB "touch" shows them) */
extern volatile uint32_t ruan_key_presses[3];
extern volatile uint32_t ruan_touch_raw_x, ruan_touch_raw_y, ruan_touch_max_x, ruan_touch_max_y;
