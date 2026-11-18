#!/bin/sh
# Pack the module zip. bootctl is AOSP's boot control client (HIDL android.hardware.boot@1.x), which HyperOS does not ship;
# pass a copy taken from a recovery ramdisk (for example OrangeFox's system/bin/bootctl). It is not kept in this repository.
set -e
[ -f "$1" ] || { echo "usage: $0 /path/to/bootctl [output.zip]"; exit 1; }
here=$(cd "$(dirname "$0")" && pwd)
out=${2:-$PWD/unixnu-dualboot.zip}
work=$(mktemp -d)
cp "$here/module.prop" "$here/action.sh" "$here/customize.sh" "$work/"
cp "$1" "$work/bootctl"
chmod 755 "$work/action.sh" "$work/bootctl"
rm -f "$out"
(cd "$work" && zip -q -r "$out" module.prop action.sh customize.sh bootctl)
rm -rf "$work"
echo "$out"
