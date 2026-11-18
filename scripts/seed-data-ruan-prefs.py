#!/usr/bin/env python3
"""Add the ruan port's Data settings to a packed Data seed (DBRDISK1), as a new seed. Run as root: the files keep their owners.

  sudo python3 scripts/seed-data-ruan-prefs.py IN.dbr OUT.dbr

From the ruan port's scripts/make-ramroot.py (SEED_PREFERENCES, DISABLED_JOBS, seed_data), which booted to the home screen:
  - mobile's preferences: Setup done, no auto-dim, no dim or lock on power, no idle sleep (dizi panicked with "cpu 1 failed to
    start" when iPadOS slept and woke), Reduce Motion and Reduce Transparency for the CPU-only renderer, no CoreAnimation
    framebuffer compression for the GOP display (also for root);
  - launchd's db/com.apple.xpc.launchd/disabled.plist: jobs that block the first boot or crash-loop without their hardware.
The volume UUID is unchanged, so the kernel's data-uuid= stays valid. The input seed is not modified.
"""
import os
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = '21H461'
CA_FRAMEBUFFER = {'CAEnableDeepFramebuffer': False, 'CAEnableFramebufferCompression': False,
                  'CAEnableIOSurfaceCompression': False}
SEED_PREFERENCES = {
    'com.apple.migration': {'LastSystemVersion': BUILD,
                            'DMUserDataDisposition': {'SyntheticDidUpgrade': False, 'buildVersion': BUILD}},
    'com.apple.springboard': {'BKNoWatchdogs': True, 'FBLaunchWatchdogExceptions': {'com.apple.purplebuddy': 100.0},
                              'MCForceShowCloudConfigurationUI': False,
                              'SBDisableAutoDim': True, 'SBDontDimOrLockOnAC': True, 'SBDisableIdleSleep': True},
    'com.apple.purplebuddy': {'SetupDone': True, 'SetupFinishedAllSteps': True, 'SetupVersion': 11,
                              'daemonizeNeedsToRun': False},
    'com.apple.purplebuddy.notbackedup': {k: False for k in (
        'ShouldRunDiagnosticsMiniBuddy', 'ShouldRunHSA2MiniBuddy', 'ShouldRunKeychainSyncMiniBuddy', 'ShouldRunMesaMiniBuddy',
        'ShouldRunPaymentMiniBuddy', 'ShouldRunStandardMiniBuddy', 'SilentICDPUpgrade')},
    'com.apple.managedconfiguration.notbackedup': {'LockdownActivationIndicatesCloudConfigurationAvailable': False},
    'backboardd': CA_FRAMEBUFFER, '.GlobalPreferences': CA_FRAMEBUFFER,
    'com.apple.Accessibility': {'ReduceMotionEnabled': True, 'ReduceMotionReduceSlideTransitionsPreference': True,
                                'EnhancedBackgroundContrastEnabled': True},
}
# iconservicesagent stays enabled: disabled, every home-screen icon is a blank placeholder (ruan rb14f).
DISABLED_JOBS = ('com.apple.watchdogd', 'com.apple.identityservicesd', 'com.apple.locationd', 'com.apple.CommCenter',
                 'com.apple.bluetoothd', 'com.apple.telephonyutilities.callservicesd', 'com.apple.fitcored',
                 'com.apple.liveactivitiesd', 'com.apple.privacyaccountingd', 'com.apple.ScreenTimeAgent', 'com.apple.dmd',
                 'com.apple.assistantd', 'com.apple.biomesyncd', 'com.apple.biomed', 'com.apple.audiomxd',
                 'com.apple.searchd', 'com.apple.siriactionsd', 'com.apple.email.maild')


def merge(path, values, uid, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = plistlib.loads(path.read_bytes()) if path.exists() else {}
    data.update(values)
    path.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY))
    os.chown(path, uid, uid)
    path.chmod(mode)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    if os.geteuid() != 0:
        raise SystemExit('Run as root (sudo): the preferences belong to mobile (501) and launchd\'s list to root.')
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    if output.exists():
        raise SystemExit(f'Refuse to overwrite {output}')
    sys.path.insert(0, str(ROOT.parent / 'UniXNU/out/dizi/ipados-17.7.11-21H461/dizi/tree/drivers/DarwinBoot/Test'))
    import packed_ramdisk
    logical, extents = packed_ramdisk.regions(source.read_bytes())
    with tempfile.TemporaryDirectory(prefix='seed-prefs-', dir=output.parent) as td:
        raw = Path(td) / 'seed.raw'
        with raw.open('wb') as handle:
            handle.truncate(logical)
            for offset, data in extents:
                handle.seek(offset)
                handle.write(data)
        mount = Path(td) / 'mnt'
        mount.mkdir()
        attached = subprocess.run(['hdiutil', 'attach', '-imagekey', 'diskimage-class=CRawDiskImage', '-nobrowse', '-owners', 'on',
                                   '-mountpoint', mount, raw], check=True, capture_output=True, text=True).stdout
        disk = re.findall(r'^/dev/(disk\d+)\s*$', attached, re.M) or [re.match(r'/dev/(disk\d+)', attached).group(1)]
        try:
            for name, values in SEED_PREFERENCES.items():
                merge(mount / 'mobile/Library/Preferences' / f'{name}.plist', values, 501, 0o600)
            for name in ('backboardd', '.GlobalPreferences'):
                merge(mount / 'root/Library/Preferences' / f'{name}.plist', CA_FRAMEBUFFER, 0, 0o600)
            launchd = mount / 'db/com.apple.xpc.launchd'
            launchd.mkdir(parents=True, exist_ok=True)
            os.chown(launchd, 0, 0)
            launchd.chmod(0o755)
            merge(launchd / 'disabled.plist', {job: True for job in DISABLED_JOBS}, 0, 0o644)
            (launchd / 'disabled.migrated').touch()
            os.chown(launchd / 'disabled.migrated', 0, 0)
            check = plistlib.loads((launchd / 'disabled.plist').read_bytes())
            assert all(check.get(job) is True for job in DISABLED_JOBS)
        finally:
            subprocess.run(['hdiutil', 'detach', disk[0], '-force'], capture_output=True)
        meta = packed_ramdisk.pack(raw, output)
    os.chown(output, int(os.environ.get('SUDO_UID', 0)), int(os.environ.get('SUDO_GID', 0)))
    print(f'{output}: {meta["encoded_bytes"]} bytes packed, {len(DISABLED_JOBS)} jobs disabled')


if __name__ == '__main__':
    main()
