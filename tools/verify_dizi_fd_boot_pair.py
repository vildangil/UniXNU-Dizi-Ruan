#!/usr/bin/env python3
"""Match a built DIZI Mu-Silicium EDK2 firmware FD to the Android boot-v4 image.

The boot kernel is gzip(BootShim + FD) followed by the board DTB. Verify exact
identity instead of assuming that an uploaded .fd belongs to the same .img.
"""
import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path


def verify_pair(boot: bytes, fd: bytes) -> dict:
    if len(boot) < 4096 or boot[:8] != b"ANDROID!":
        raise ValueError("missing Android boot image header")
    kernel_size = struct.unpack_from("<I", boot, 8)[0]
    version = struct.unpack_from("<I", boot, 40)[0]
    if version != 4 or kernel_size < 100 or 4096 + kernel_size > len(boot):
        raise ValueError("expected Android boot v4 with a bounded kernel")
    if len(fd) < 72 or fd[40:44] != b"_FVH":
        raise ValueError("raw firmware FD is invalid")
    gz = zlib.decompressobj(31)
    raw = gz.decompress(boot[4096:4096+kernel_size]) + gz.flush()
    dtb = gz.unused_data
    if not gz.eof or len(dtb) < 40 or dtb[:4] != b"\xd0\x0d\xfe\xed":
        raise ValueError("missing gzip end marker or board DTB")
    if len(raw) != len(fd) + 0x70 or raw[0x70:] != fd:
        raise ValueError("boot image does not contain the exact companion EDK2 FD")
    return {
        "status": "FD_MATCHES_BOOT_IMAGE_EXACTLY",
        "firmware_sha256": hashlib.sha256(fd).hexdigest(),
        "boot_img_sha256": hashlib.sha256(boot).hexdigest(),
        "android_boot_version": 4,
        "bootshim_size": 0x70,
        "fd_bytes": len(fd),
        "dtb_bytes": len(dtb),
        "hardware_boot_verified": False,
        "keypad_functional": False,
        "usb_host_functional": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("boot", type=Path)
    p.add_argument("fd", type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    report = verify_pair(a.boot.read_bytes(), a.fd.read_bytes())
    output = json.dumps(report, indent=2) + "\n"
    print(output)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(output)


if __name__ == "__main__":
    main()
