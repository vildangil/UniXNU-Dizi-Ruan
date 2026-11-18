// SPDX-License-Identifier: BSD-2-Clause-Patent
// RuanAudioProbe: Qualcomm LPASS SoundWire & Quad WSA883x Smart Amplifiers probe for ruan.
#ifndef RUAN_AUDIO_PROBE_H
#define RUAN_AUDIO_PROBE_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define LPASS_WSA_BASE              0x031E0000ULL
#define LPASS_WSA_SIZE              0x00010000ULL  /* 64 KiB */
#define LPASS_WSA_SWR1_BASE         0x03210000ULL
#define LPASS_WSA_SWR4_BASE         0x03230000ULL

struct ruan_audio_telemetry {
    int probed;
    int swr1_mapped;
    int swr4_mapped;
    uint32_t swr1_val;
    uint32_t swr4_val;
    char status[64];
};

extern struct ruan_audio_telemetry g_ruan_audio;

void ruan_audio_init(void);
const char *ruan_audio_status_str(void);

#ifdef __cplusplus
}
#endif

#endif // RUAN_AUDIO_PROBE_H
