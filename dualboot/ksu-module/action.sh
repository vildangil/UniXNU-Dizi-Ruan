#!/system/bin/sh
# UniXNU dual boot for dizi: boot iPadOS from slot b exactly once.
#
# Slot b holds the UniXNU image in boot_b; every other slot-b partition is the same firmware as slot a. The boot control
# HAL (bootctl) makes slot b active, as "fastboot set_active b" does: it also swaps the partition type GUIDs and the UFS
# boot LUN. Then boot_b gets one retry and stays unsuccessful, so the bootloader boots it once and, on the next reboot,
# marks slot b unbootable and switches back to slot a (Android) by itself.
MODDIR=${0%/*}
BOOTCTL=$MODDIR/bootctl
die() { echo "! $*"; exit 1; }
# After the switch, any failure goes back to slot a, so the tablet never stays on slot b with several retries.
undo() { echo "! $*"; "$BOOTCTL" set-active-boot-slot 0 && echo "- Slot a is active again; nothing else changed."; exit 1; }

slot=$(getprop ro.boot.slot_suffix)
[ "$slot" = "_a" ] || die "Android must run from slot a (now: $slot)"
[ -f "$BOOTCTL" ] || die "bootctl missing in $MODDIR"
[ -x "$BOOTCTL" ] || chmod 0755 "$BOOTCTL" || die "cannot make $BOOTCTL executable"

link=$(readlink -f /dev/block/by-name/boot_b) || die "no boot_b"
disk=${link%%[0-9]*}
part=${link#$disk}
[ -b "$disk" ] && [ -n "$part" ] || die "cannot resolve boot_b ($link)"

# boot_b must hold the UniXNU image (Mu-Silicium UEFI and the UniXNU payload), not Android or an empty partition.
head -c 8 "$link" | grep -q 'ANDROID!' || die "boot_b is not a boot image"
dd if="$link" bs=1048576 count=64 2>/dev/null | grep -aq 'UniXNU' || die "boot_b does not hold the UniXNU image"

echo "- Switching to slot b (boot control HAL)"
"$BOOTCTL" set-active-boot-slot 1 || die "bootctl set-active-boot-slot 1 failed"

echo "- One try for boot_b ($disk entry $part)"
sgdisk --attributes="$part":set:51 --attributes="$part":clear:52 --attributes="$part":clear:53 "$disk" >/dev/null 2>&1 ||
  undo "sgdisk could not set the retry count"
attrs=$(sgdisk --info="$part" "$disk" | sed -n 's/^Attribute flags: //p')
echo "- boot_b attributes: $attrs"
case $attrs in
  000F*) ;;   # priority 3, active, one retry, not successful, not unbootable
  *) undo "unexpected boot_b attributes $attrs; not rebooting" ;;
esac

echo "- Rebooting into iPadOS. The next reboot returns to Android."
sleep 2
reboot
