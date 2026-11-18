// SPDX-License-Identifier: BSD-2-Clause-Patent
// Read-only file access and the kernel message buffer over ruan's USB CDC terminal (package/UsbDebugCdc.cpp).
// Included by UsbDebugCdc.cpp inside its anonymous namespace, after UsbDebugCommands.h (UsbReplyRing).
//
//   ls <dir>      RUANL <type> <size> <name>\r\n ... RUANL END <count> <errno>\r\n
//   cat <path>    RUANF BEGIN <id> <size> <path>\r\n, then RUANF D <id> <offset> <base64 of <= 768 bytes>\r\n ...,
//                 then RUANF END <id> <bytes> <crc32 hex>\r\n   (or RUANF ERR <id> <errno> <what>\r\n)
//   dmesg         the same framing with path "msgbuf": a snapshot of the whole kernel message buffer (msgbufp)
//
// Base64 keeps the stream text-only, so a file can never look like a GSC1 screen header to the host's decoder. Files are
// streamed from the debug thread a chunk at a time while the reply ring has room; nothing is ever written.

#ifndef RUAN_USB_DEBUG_FILES_H
#define RUAN_USB_DEBUG_FILES_H

static const uint32_t kFileCap = 8u << 20;          // cat refuses larger files (and dmesg is far below it)
static const uint32_t kFileChunk = 768u;            // raw bytes per line: 1024 base64 characters

struct UsbFileXfer {
    bool active;
    uint32_t id;
    vnode_t vp;                 // file source (iocount + usecount from vnode_open), or
    uint8_t *mem;               // memory source (dmesg snapshot, IOMalloc'd)
    uint32_t memCap;
    uint32_t size, off, crc;
};

static vfs_context_t usbVfsContext() {
    static vfs_context_t ctx;   // the debug thread is the only user
    if (!ctx) ctx = vfs_context_create(nullptr);
    return ctx;
}

static void usbB64(const uint8_t *in, uint32_t n, char *out) {
    static const char k[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    uint32_t o = 0;
    for (uint32_t i = 0; i < n; i += 3) {
        const uint32_t v = (uint32_t)in[i] << 16 | (i + 1 < n ? (uint32_t)in[i + 1] << 8 : 0u) | (i + 2 < n ? in[i + 2] : 0u);
        out[o++] = k[(v >> 18) & 63];
        out[o++] = k[(v >> 12) & 63];
        out[o++] = i + 1 < n ? k[(v >> 6) & 63] : '=';
        out[o++] = i + 2 < n ? k[v & 63] : '=';
    }
    out[o] = '\0';
}

static int usbVnodeSize(vnode_t vp, uint64_t *size) {
    struct vnode_attr va;
    VATTR_INIT(&va);
    VATTR_WANTED(&va, va_data_size);
    const int err = vnode_getattr(vp, &va, usbVfsContext());
    *size = (!err && VATTR_IS_SUPPORTED(&va, va_data_size)) ? va.va_data_size : 0;
    return err;
}

static void usbFileEnd(UsbFileXfer &x) {
    if (x.vp) vnode_close(x.vp, FREAD, usbVfsContext());
    if (x.mem) IOFree(x.mem, x.memCap);
    x.vp = nullptr;
    x.mem = nullptr;
    x.active = false;
}

static void usbFileErr(UsbReplyRing &reply, uint32_t id, int err, const char *what) {
    char line[160];
    snprintf(line, sizeof(line), "RUANF ERR %u %d %s\r\n", id, err, what);
    reply.writeStr(line);
}

static void usbFileBegin(UsbFileXfer &x, UsbReplyRing &reply, const char *name) {
    char line[320];
    x.active = true;
    x.off = 0;
    x.crc = 0;
    snprintf(line, sizeof(line), "\r\nRUANF BEGIN %u %u %s\r\n", x.id, x.size, name);
    reply.writeStr(line);
}

static void usbCatStart(UsbFileXfer &x, UsbReplyRing &reply, const char *path) {
    if (x.active) usbFileEnd(x);
    ++x.id;
    vnode_t vp = nullptr;
    int err = vnode_open(path, FREAD, 0, 0, &vp, usbVfsContext());
    if (err) { usbFileErr(reply, x.id, err, "open"); return; }
    if (vnode_vtype(vp) != VREG) {
        vnode_close(vp, FREAD, usbVfsContext());
        usbFileErr(reply, x.id, EISDIR, "not a regular file (use ls)");
        return;
    }
    uint64_t size = 0;
    err = usbVnodeSize(vp, &size);
    if (err || size > kFileCap) {
        vnode_close(vp, FREAD, usbVfsContext());
        usbFileErr(reply, x.id, err ? err : EFBIG, err ? "getattr" : "larger than the 8 MiB cap");
        return;
    }
    x.vp = vp;
    x.size = static_cast<uint32_t>(size);
    usbFileBegin(x, reply, path);
}

static void usbDmesgStart(UsbFileXfer &x, UsbReplyRing &reply) {
    if (x.active) usbFileEnd(x);
    ++x.id;
    struct msgbuf *mb = msgbufp;
    if (!mb || mb->msg_magic != MSG_MAGIC || mb->msg_size <= 0 || mb->msg_size > MAX_MSG_BSIZE || !mb->msg_bufc) {
        usbFileErr(reply, x.id, ENXIO, "no msgbuf");
        return;
    }
    const uint32_t size = static_cast<uint32_t>(mb->msg_size);
    uint8_t *copy = static_cast<uint8_t *>(IOMalloc(size));
    if (!copy) { usbFileErr(reply, x.id, ENOMEM, "snapshot"); return; }
    // Oldest byte first: the ring starts at the write pointer. NULs (never-written space) are dropped.
    uint32_t n = 0, w = static_cast<uint32_t>(mb->msg_bufx);
    if (w >= size) w = 0;
    for (uint32_t i = 0; i < size; ++i) {
        const char c = mb->msg_bufc[(w + i) % size];
        if (c) copy[n++] = static_cast<uint8_t>(c);
    }
    x.mem = copy;
    x.memCap = size;
    x.size = n;
    usbFileBegin(x, reply, "msgbuf");
}

// Called from the debug loop: adds lines while the reply ring has room, ends the transfer when done.
static void usbFilePump(UsbFileXfer &x, UsbReplyRing &reply) {
    uint8_t raw[kFileChunk];
    char line[64 + kFileChunk * 4 / 3 + 8];
    while (x.active && reply.freeBytes() > sizeof(line) + 128u) {
        const uint32_t want = (x.size - x.off) < kFileChunk ? (x.size - x.off) : kFileChunk;
        uint32_t got = 0;
        if (want && x.mem) {
            memcpy(raw, x.mem + x.off, want);
            got = want;
        } else if (want) {
            uio_t uio = uio_create(1, x.off, UIO_SYSSPACE, UIO_READ);
            if (!uio) { usbFileErr(reply, x.id, ENOMEM, "uio"); usbFileEnd(x); return; }
            uio_addiov(uio, CAST_USER_ADDR_T(raw), want);
            const int err = VNOP_READ(x.vp, uio, 0, usbVfsContext());
            got = want - static_cast<uint32_t>(uio_resid(uio));
            uio_free(uio);
            if (err || !got) {
                usbFileErr(reply, x.id, err ? err : EIO, "read (file shorter than its size?)");
                usbFileEnd(x);
                return;
            }
        }
        if (!got) {
            snprintf(line, sizeof(line), "RUANF END %u %u %08x\r\n", x.id, x.off, x.crc);
            reply.writeStr(line);
            usbFileEnd(x);
            return;
        }
        x.crc = usb_crc32_update(x.crc, raw, got);
        int n = snprintf(line, sizeof(line), "RUANF D %u %u ", x.id, x.off);
        usbB64(raw, got, line + n);
        strlcat(line, "\r\n", sizeof(line));
        reply.writeStr(line);
        x.off += got;
    }
}

static void usbLs(UsbReplyRing &reply, const char *dir) {
    char line[MAXPATHLEN + 64];
    vnode_t vp = nullptr;
    unsigned count = 0;
    int err = vnode_open(dir, FREAD, 0, 0, &vp, usbVfsContext());
    if (!err && vnode_vtype(vp) != VDIR) {
        vnode_close(vp, FREAD, usbVfsContext());
        err = ENOTDIR;
    }
    if (!err) {
        uint8_t *buf = static_cast<uint8_t *>(IOMalloc(8192));
        off_t pos = 0;
        int eof = 0;
        while (buf && !eof && count < 4000u) {
            uio_t uio = uio_create(1, pos, UIO_SYSSPACE, UIO_READ);
            if (!uio) { err = ENOMEM; break; }
            uio_addiov(uio, CAST_USER_ADDR_T(buf), 8192);
            int entries = 0;
            err = VNOP_READDIR(vp, uio, 0, &eof, &entries, usbVfsContext());
            const uint32_t used = 8192u - static_cast<uint32_t>(uio_resid(uio));
            pos = uio_offset(uio);
            uio_free(uio);
            if (err || !used) break;
            for (uint32_t at = 0; at + offsetof(struct dirent, d_name) < used;) {
                const struct dirent *d = reinterpret_cast<const struct dirent *>(buf + at);
                if (!d->d_reclen) break;
                at += d->d_reclen;
                char name[MAXNAMLEN + 1];
                const unsigned len = d->d_namlen < MAXNAMLEN ? d->d_namlen : MAXNAMLEN;
                memcpy(name, d->d_name, len);
                name[len] = '\0';
                if (!d->d_ino || !strcmp(name, ".") || !strcmp(name, "..")) continue;
                char full[MAXPATHLEN];
                snprintf(full, sizeof(full), "%s/%s", dir, name);
                uint64_t size = 0;
                vnode_t ep = nullptr;
                if (d->d_type == DT_REG && !vnode_lookup(full, 0, &ep, usbVfsContext())) {
                    (void)usbVnodeSize(ep, &size);
                    vnode_put(ep);
                }
                const char t = d->d_type == DT_DIR ? 'd' : d->d_type == DT_REG ? 'f' : d->d_type == DT_LNK ? 'l' : '?';
                snprintf(line, sizeof(line), "RUANL %c %llu %s\r\n", t, (unsigned long long)size, name);
                if (reply.freeBytes() < strlen(line) + 64u) { err = ENOBUFS; break; }
                reply.writeStr(line);
                ++count;
            }
            if (err) break;
        }
        if (buf) IOFree(buf, 8192);
        else err = ENOMEM;
        vnode_close(vp, FREAD, usbVfsContext());
    }
    snprintf(line, sizeof(line), "RUANL END %u %d\r\n", count, err);
    reply.writeStr(line);
}

#endif // RUAN_USB_DEBUG_FILES_H
