#!/usr/bin/env python3
"""dizi: copied unchanged from the ruan port (F-e-n-y-x/UniXNU-iPadOS-on-Redmi-Pad-Pro-5G, tools/, commit 72cc448). On macOS pass
--tty /dev/cu.usbmodemRUANDBG* (the default lookup reads Linux sysfs). debug_screen.py is UniXNU's scripts/debug_screen.py.

Host side of ruan's live XNU USB terminal (package/UsbDebugCdc.cpp, boot-arg ruan-usbdbg=1). Runs on zima, stdlib only.

The tablet enumerates as a CDC-ACM serial device 1209:0001 "Redmi Pad Pro 5G Debug CDC" (Linux: /dev/ttyACM*).

  ruan-usbdbg.py log [--seconds N]          stream the kernel/boot log (ramoops console zone) to stdout + logs/usb-<time>.log
  ruan-usbdbg.py cmd status [--wait 2]      send one command (status display usb touch bootargs replay reboot.status ...)
  ruan-usbdbg.py shot [-o x.png] [--edge N] grab the screen (GOP scanout) as a PNG; --edge = longest side, 160..1264
  ruan-usbdbg.py ls <dir>                   list a directory on the tablet (read-only)
  ruan-usbdbg.py get <path> [-o file]       copy one file off the tablet (<= 8 MiB, CRC-checked)
  ruan-usbdbg.py dmesg [-o file]            the whole kernel message buffer (msgbufp)
  ruan-usbdbg.py pull-crashes [-d dir]      every .ips under CrashReporter (and its Retired/ folder) into dir
  ruan-usbdbg.py reboot                     PSCI reset with no reboot reason: a normal boot (Android); then `adb reboot bootloader`
  ruan-usbdbg.py reboot-fastboot            mark "bootloader" in the PMIC, then reset; each step is printed first
                                            (both reboots need ruan-usbdbg-reboot=1 on the kernel command line)

Only one ruan-usbdbg.py can use the tty at a time (flock); a second one exits with a message.

debug_screen.py (next to this file) is UniXNU's scripts/debug_screen.py: the GSC1 frame decoder and PNG writer.
"""
import argparse, base64, binascii, fcntl, glob, os, pathlib, re, sys, termios, time, tty

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from debug_screen import ScreenWire, rgb565_png   # noqa: E402

VID, PID = '1209', '0001'


def find_tty():
    for dev in glob.glob('/sys/bus/usb/devices/*'):
        try:
            if open(dev + '/idVendor').read().strip() == VID and open(dev + '/idProduct').read().strip() == PID:
                ttys = glob.glob(dev + '/*/tty/tty*') + glob.glob(dev + '/*/tty*')
                names = sorted({os.path.basename(t) for t in ttys if os.path.basename(t).startswith('ttyACM')})
                if names:
                    return '/dev/' + names[0]
        except OSError:
            continue
    return None


def open_tty(path):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # log/shot/get share one CDC stream: one user at a time
    except BlockingIOError:
        sys.exit(f'ruan-usbdbg: {path} is in use by another ruan-usbdbg.py (stop the `log` reader first)')
    tty.setraw(fd)                      # cdc_acm raises DTR on open: the tablet then marks the host ready
    attrs = termios.tcgetattr(fd)
    attrs[2] |= termios.CLOCAL
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def read_for(fd, seconds, wire, on_text, stop=None):
    end = time.time() + seconds
    while time.time() < end:
        try:
            data = os.read(fd, 65536)
        except BlockingIOError:
            time.sleep(0.01)
            continue
        if not data:
            time.sleep(0.01)
            continue
        if wire:
            text, frames = wire.feed(data)
            if text:
                on_text(text)
        else:
            frames = []
            on_text(data)
        if stop and stop(frames):
            return True
    return False


def send(fd, line, timeout=5.0):
    """Write one command line whole. The tty is non-blocking: drain stale input first (it would otherwise be parsed with the
    next reply), lead with CR LF so a half-sent earlier line ends on the device as its own (ignored or rejected) command, then
    write until every byte is out, retrying on EAGAIN and partial writes (rb18g1: EAGAIN garbled "gpu 4")."""
    while True:
        try:
            if not os.read(fd, 65536):
                break
        except BlockingIOError:
            break
    data = b'\r\n' + line.encode() + b'\r\n'
    end = time.time() + timeout
    while data:
        try:
            data = data[os.write(fd, data):]
        except BlockingIOError:
            if time.time() > end:
                sys.exit(f'ruan-usbdbg: timed out sending {line!r}')
            time.sleep(0.01)
    termios.tcdrain(fd)


class Lines:
    """Collects the text stream and hands out complete lines (the device never splits one of its own lines)."""
    def __init__(self, echo=None):
        self.buf, self.lines, self.echo = bytearray(), [], echo

    def __call__(self, data):
        self.buf.extend(data)
        while True:
            i = self.buf.find(b'\n')
            if i < 0:
                break
            line = bytes(self.buf[:i]).rstrip(b'\r')
            del self.buf[:i + 1]
            self.lines.append(line)
            if self.echo and not line.startswith((b'RUANF ', b'RUANL ')):
                self.echo(line + b'\n')


FILE_RE = re.compile(rb'RUANF (BEGIN|D|END|ERR) (\d+) (.*)')


def fetch(fd, wire, command, timeout):
    """Run cat/dmesg; return (name, bytes). Raises RuntimeError with the device's reason."""
    lines = Lines()
    send(fd, command)
    state = {}
    def done(_frames):
        while lines.lines:
            m = FILE_RE.search(lines.lines.pop(0))
            if not m:
                continue
            kind, fid, rest = m.group(1), int(m.group(2)), m.group(3)
            if kind == b'BEGIN' and 'id' not in state:
                size, name = rest.split(b' ', 1)
                state.update(id=fid, size=int(size), name=name.decode(errors='replace'), data=bytearray())
            elif fid != state.get('id') and kind != b'ERR':
                continue
            elif kind == b'D':
                off, b64 = rest.split(b' ', 1)
                if int(off) != len(state['data']):
                    raise RuntimeError(f'gap at {int(off)} (have {len(state["data"])})')
                state['data'].extend(base64.b64decode(b64))
            elif kind == b'END':
                n, crc = rest.split(b' ')
                if int(n) != len(state['data']) or int(crc, 16) != binascii.crc32(state['data']):
                    raise RuntimeError('length/CRC mismatch')
                state['ok'] = True
                return True
            elif kind == b'ERR':
                raise RuntimeError(rest.decode(errors='replace'))
        return False
    if not read_for(fd, timeout, None, lines, done):
        raise RuntimeError(f'timeout after {timeout:.0f} s ({len(state.get("data", b""))} bytes)')
    return state['name'], bytes(state['data'])


def listdir(fd, wire, path, timeout=20.0):
    lines, entries, end = Lines(), [], {}
    send(fd, 'ls ' + path)
    def done(_frames):
        while lines.lines:
            line = lines.lines.pop(0)
            if not line.startswith(b'RUANL '):
                continue
            parts = line.split(b' ', 3)
            if parts[1] == b'END':
                end['count'], end['err'] = int(parts[2]), int(parts[3])
                return True
            entries.append((parts[1].decode(), int(parts[2]), parts[3].decode(errors='replace')))
        return False
    if not read_for(fd, timeout, None, lines, done):
        raise RuntimeError('timeout')
    if end['err']:
        raise RuntimeError(f'errno {end["err"]} ({os.strerror(end["err"])})')
    return entries


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tty', help='serial device (default: find 1209:0001)')
    sub = ap.add_subparsers(dest='what', required=True)
    p = sub.add_parser('log'); p.add_argument('--seconds', type=float, default=1e9)
    p = sub.add_parser('cmd'); p.add_argument('text', nargs='+'); p.add_argument('--wait', type=float, default=2.0)
    p = sub.add_parser('shot'); p.add_argument('-o', '--output'); p.add_argument('--edge', type=int, default=1264)
    p.add_argument('--timeout', type=float, default=60.0)
    sub.add_parser('reboot-fastboot')
    sub.add_parser('reboot')
    p = sub.add_parser('ls'); p.add_argument('path')
    p = sub.add_parser('get'); p.add_argument('path'); p.add_argument('-o', '--output'); p.add_argument('--timeout', type=float, default=300.0)
    p = sub.add_parser('dmesg'); p.add_argument('-o', '--output'); p.add_argument('--timeout', type=float, default=180.0)
    p = sub.add_parser('pull-crashes'); p.add_argument('-d', '--dir', default='crashes')
    a = ap.parse_args()

    path = a.tty or find_tty()
    if not path:
        sys.exit('ruan-usbdbg: no 1209:0001 CDC device (is the tablet booted with ruan-usbdbg=1? check `lsusb`, dmesg)')
    fd = open_tty(path)
    wire = ScreenWire()
    out = lambda b: (sys.stdout.write(b.decode('utf-8', 'replace')), sys.stdout.flush())

    if a.what == 'log':
        logs = pathlib.Path('logs'); logs.mkdir(exist_ok=True)
        log = open(logs / time.strftime('usb-%Y%m%d-%H%M%S.log'), 'ab')
        def both(b):
            out(b); log.write(b); log.flush()
        send(fd, 'replay')
        read_for(fd, a.seconds, wire, both)
    elif a.what == 'cmd':
        send(fd, ' '.join(a.text))
        read_for(fd, a.wait, wire, out)
    elif a.what == 'shot':
        send(fd, f'screen.configure {a.edge} 1')
        got = []
        def first_frame(frames):
            got.extend(frames)
            return bool(got)
        send(fd, 'screen.snapshot')
        if not read_for(fd, a.timeout, wire, out, first_frame):
            sys.exit(f'ruan-usbdbg: no frame in {a.timeout:.0f} s (decode errors: {wire.errors})')
        _, _, w, h, pixels = got[0]
        name = a.output or time.strftime('screen-%Y%m%d-%H%M%S.png')
        pathlib.Path(name).write_bytes(rgb565_png(w, h, pixels))
        print(f'\nruan-usbdbg: wrote {name} ({w}x{h})')
    elif a.what in ('reboot', 'reboot-fastboot'):
        send(fd, 'reboot.fastboot' if a.what == 'reboot-fastboot' else 'reboot')
        read_for(fd, 5.0, wire, out)   # the device prints each step, then drops off the bus
    elif a.what == 'ls':
        for t, size, name in listdir(fd, wire, a.path):
            print(f'{t} {size:>10} {name}')
    elif a.what in ('get', 'dmesg'):
        try:
            name, data = fetch(fd, wire, 'dmesg' if a.what == 'dmesg' else 'cat ' + a.path,
                               a.timeout)
        except RuntimeError as e:
            sys.exit(f'ruan-usbdbg: {a.what} failed: {e}')
        if a.what == 'dmesg' and not a.output:
            sys.stdout.write(data.decode('utf-8', 'replace'))
        else:
            dest = a.output or os.path.basename(a.path)
            pathlib.Path(dest).write_bytes(data)
            print(f'ruan-usbdbg: {name} -> {dest} ({len(data)} bytes, CRC ok)')
    elif a.what == 'pull-crashes':
        base = '/private/var/mobile/Library/Logs/CrashReporter'
        dest = pathlib.Path(a.dir); dest.mkdir(exist_ok=True)
        got = 0
        for folder in (base, base + '/Retired'):
            try:
                entries = listdir(fd, wire, folder)
            except RuntimeError as e:
                print(f'ruan-usbdbg: ls {folder}: {e}')
                continue
            for t, size, name in entries:
                if t != 'f' or not name.endswith('.ips'):
                    continue
                try:
                    _, data = fetch(fd, wire, f'cat {folder}/{name}', 120.0)
                except RuntimeError as e:
                    print(f'ruan-usbdbg: {name}: {e}')
                    continue
                (dest / name).write_bytes(data)
                got += 1
                print(f'{name} ({len(data)} bytes)')
        print(f'ruan-usbdbg: {got} crash report(s) in {dest}/')
    os.close(fd)


if __name__ == '__main__':
    main()
