#!/usr/bin/env python3
"""Shorten IOMobileGraphicsFamily's swap wait in a prelinked dizi kernel.macho (a copy: IN is not modified).

  python3 scripts/patch-iomfb-swap-wait.py IN.macho OUT.macho [--ms 33]

swap_wait_gated (selector 6, the compositor's wait for its swap) sleeps on the family's command gate with a fixed 5 s deadline:
    mov w8,#5000 ; stur w8,[x29,#-148] ; sub x2,x29,#160 ; ... ; mov w1,#1000000 ; bl clock_interval_to_deadline
The GOP display has no vblank or swap-complete interrupt, so the CommandWake that ends the wait often never comes: the family logs
"CommandWake didn't happen even after 5 seconds ... cancelling swaps", calls slot 345 (GopFramebuffer's cancelSwapsAfterTimeout,
NATIVE_LEGACY_CANCEL_SWAPS) and returns, and backboardd draws its next frame. Every frame cost 5 s (0.2-0.35 fps on dizi). With the
deadline at --ms (default 33, two 60 Hz frames) the same timeout path runs after one frame time instead.

Only the 16-bit immediate of the one `mov w8,#5000` that is followed by that exact sequence changes; the script refuses a kernel
where the sequence is missing or not unique, so another build is left alone.
"""
import argparse
import struct
from pathlib import Path

MOV_W8_5000 = 0x52827108
# What follows it in 21H461: stur w8,[x29,#-148] ; sub x2,x29,#160 ; mov x8,#0xaaaaaaaaaaaaaaaa ; stur x8,[x29,#-160] ;
# stur xzr,[x29,#-160] ; ldur w0,[x29,#-148] ; mov w1,#0x4240 ; movk w1,#0xf,lsl #16  (5000 x 1000000 ns)
FOLLOW = (0xb816c3a8, 0xd10283a2, 0xb201f3e8, 0xf81603a8, 0xf81603bf, 0xb856c3a0, 0x52884801, 0x72a001e1)

def words(data, at, n):
    return struct.unpack_from(f'<{n}I', data, at)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('--ms', type=int, default=33)
    args = parser.parse_args()
    if not 1 <= args.ms <= 5000:
        raise SystemExit('--ms must be 1..5000')
    data = bytearray(Path(args.input).read_bytes())
    needle = struct.pack('<I', MOV_W8_5000)
    sites = []
    start = 0
    while (at := data.find(needle, start)) >= 0:
        start = at + 1
        if at % 4:
            continue
        if words(data, at + 4, len(FOLLOW)) == FOLLOW:
            sites.append(at)
    if len(sites) != 1:
        raise SystemExit(f'{args.input}: expected one swap_wait_gated 5 s deadline, found {len(sites)}; not patched')
    at = sites[0]
    data[at:at + 4] = struct.pack('<I', 0x52800008 | (args.ms << 5))
    Path(args.output).write_bytes(data)
    print(f'{args.output}: swap wait {args.ms} ms (file offset {at:#x})')


if __name__ == '__main__':
    main()
