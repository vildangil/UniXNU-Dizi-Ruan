#!/bin/bash
# GPU (Adreno 710) preparation for dizi, following the ruan port's agy-15-11-26 branch (docs/research/gpu-adreno710.md,
# gpu-metal-turnip-roadmap.md). Downloads and installs nothing by itself:
#   1. checks the host tools the Mesa/Turnip and metal2vulkan builds need (MacPorts, no Homebrew) and prints what is missing;
#   2. with the tablet in Android (adb, root through KernelSU), copies the GPU firmware to .cache/gpu-fw (vendor firmware: never committed).
#
#   tools/gpu-prep.sh            both steps
#   tools/gpu-prep.sh tools      only the host check
#   tools/gpu-prep.sh firmware   only the firmware copy
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/.cache/gpu-fw"
FIRMWARE=(a710_sqe.fw gmu_gen70000.bin a710_zap.mdt a710_zap.b00 a710_zap.b01 a710_zap.b02)
export PATH="/opt/local/bin:/opt/local/sbin:$PATH"

check_tools() {
    local missing=() t
    # command : MacPorts port
    for t in meson:meson ninja:ninja cmake:cmake pkg-config:pkgconfig bison:bison flex:flex cargo:cargo rustc:rust glslangValidator:glslang \
             python3.12:python312; do
        command -v "${t%%:*}" >/dev/null 2>&1 && echo "ok       ${t%%:*}" || { echo "missing  ${t%%:*}"; missing+=("${t#*:}"); }
    done
    # MacPorts' python3.12 (another python3 may come first in PATH)
    python3.12 -c 'import mako, yaml' 2>/dev/null && echo "ok       python mako, yaml" || { echo "missing  python mako, yaml"; missing+=(py312-mako py312-yaml); }
    xcrun --find metal >/dev/null 2>&1 && echo "ok       xcrun metal" || echo "missing  xcrun metal (Xcode's Metal toolchain: xcodebuild -downloadComponent MetalToolchain)"
    if ((${#missing[@]})); then
        echo; echo "Install with (sudo asks for your password; type it yourself):"; echo "  sudo port install ${missing[*]}"
    fi
}

pull_firmware() {
    command -v adb >/dev/null || { echo "adb not found"; return 1; }
    adb get-state >/dev/null 2>&1 || { echo "no tablet over adb: boot Android, plug in, accept the debugging prompt"; return 1; }
    mkdir -p "$OUT"
    local f dir found
    for f in "${FIRMWARE[@]}"; do
        found=""
        for dir in /vendor/firmware /vendor/firmware_mnt/image /odm/firmware /system/vendor/firmware; do
            if adb shell su -c "test -f $dir/$f" 2>/dev/null; then
                adb shell su -c "cat $dir/$f" > "$OUT/$f" && found="$dir/$f"; break
            fi
        done
        if [ -n "$found" ]; then echo "copied   $found ($(wc -c < "$OUT/$f") bytes)"; else echo "absent   $f"; rm -f "$OUT/$f"; fi
    done
    (cd "$OUT" && shasum -a 256 * > SHA256SUMS 2>/dev/null; cat SHA256SUMS)
}

case "${1:-all}" in
    tools) check_tools ;;
    firmware) pull_firmware ;;
    all) check_tools; echo; pull_firmware ;;
    *) sed -n 2,9p "$0"; exit 2 ;;
esac
