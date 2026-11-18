// SPDX-License-Identifier: BSD-2-Clause-Patent
// RuanA710Pm4.h: Adreno 710 (A7xx) PM4 Packet Definitions and Helpers.
#ifndef RUAN_A710_PM4_H
#define RUAN_A710_PM4_H

#include <stdint.h>

static inline uint32_t pm4_calc_odd_parity_bit(uint32_t val)
{
	return (0x9669 >> (0xf & ((val) ^
		((val) >> 4) ^ ((val) >> 8) ^ ((val) >> 12) ^
		((val) >> 16) ^ ((val) >> 20) ^ ((val) >> 24) ^
		((val) >> 28)))) & 1;
}

static inline uint32_t cp_type7_packet(uint32_t opcode, uint32_t cnt)
{
	return (7u << 28) | ((cnt) & 0x3fffu)  /* bits 0-13; bit 15 is the count parity */ |
		(pm4_calc_odd_parity_bit(cnt) << 15) |
		(((opcode) & 0x7fu) << 16) |
		(pm4_calc_odd_parity_bit(opcode) << 23);
}

#define CP_NOP                              0x10u
#define CP_WAIT_MEM_WRITES                  0x12u
#define CP_WAIT_FOR_ME                      0x13u
#define CP_THREAD_CONTROL                   0x17u
#define CP_WAIT_FOR_IDLE                    0x26u
#define CP_MEM_WRITE                        0x3du
#define CP_EVENT_WRITE7                     0x46u
#define CP_ME_INIT                          0x48u
#define CP_SET_SECURE_MODE                  0x66u
#define CP_MEM_TO_MEM                       0x73u
#define CP_MEMCPY                           0x75u

#endif // RUAN_A710_PM4_H
