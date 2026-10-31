.section .text.trace,"ax",%progbits
.p2align 2
trace_hit_1:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_1
 movz w13,#1
 b trace_common
trace_resume_1:
 ldp x12,x13,[sp],#16
 .inst 0xaa0103fa
 .inst 0x17ffdf72
trace_hit_2:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_2
 movz w13,#2
 b trace_common
trace_resume_2:
 ldp x12,x13,[sp],#16
 .inst 0xf0ffebc8
 .inst 0x17ffdff2
trace_hit_3:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_3
 movz w13,#3
 b trace_common
trace_resume_3:
 ldp x12,x13,[sp],#16
 .inst 0xf9400108
 .inst 0x17ffe22e
trace_hit_4:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_4
 movz w13,#4
 b trace_common
trace_resume_4:
 ldp x12,x13,[sp],#16
 .inst 0xf0ffebc8
 .inst 0x17ffe212
trace_common:
    sub sp,sp,#0xb0
    stp x0,x1,[sp,#0]
    stp x2,x3,[sp,#16]
    stp x4,x5,[sp,#32]
    stp x6,x7,[sp,#48]
    stp x8,x9,[sp,#64]
    stp x10,x11,[sp,#80]
    stp x12,x13,[sp,#96]
    stp x14,x15,[sp,#112]
    stp x16,x17,[sp,#128]
    stp x18,x30,[sp,#144]
    mrs x9,NZCV
    str x9,[sp,#160]
    mov w0,w13
    bl trace_render
    ldr x9,[sp,#104]
    cmp w9,#4
    b.ne stack_skip
    bl stack_snapshot
stack_skip:
    ldr x9,[sp,#160]
    msr NZCV,x9
    ldp x0,x1,[sp,#0]
    ldp x2,x3,[sp,#16]
    ldp x4,x5,[sp,#32]
    ldp x6,x7,[sp,#48]
    ldp x8,x9,[sp,#64]
    ldp x10,x11,[sp,#80]
    ldp x12,x13,[sp,#96]
    ldp x14,x15,[sp,#112]
    ldp x16,x17,[sp,#128]
    ldp x18,x30,[sp,#144]
    add sp,sp,#0xb0
    br x12
trace_render:
    // First 2MiB only: fb high alias + 650*4 + 6400*(10+34*stage)
    movz x9,#0
    movk x9,#0x0400,lsl#16
    movk x9,#0xfff0,lsl#32
    movk x9,#0xffff,lsl#48
    cmp w0,#1
    b.ne trace_no_clear
    movz x10,#2,lsl#16
    mov x11,x9
trace_clear:
    stp xzr,xzr,[x11],#16
    subs x10,x10,#1
    b.ne trace_clear
    dsb sy
trace_no_clear:
    movz x10,#80
    cmp w0,#8
    b.hi trace_left
    movz x10,#80
trace_left:
    add x9,x9,x10
    mov x2,x0
    cmp w2,#8
    b.ls trace_row
    sub w2,w2,#8
trace_row:
    movz x1,#34
    mul x1,x2,x1
    add x1,x1,#10
    movz x3,#6400
    madd x7,x1,x3,x9
    cmp w0,#1
    b.eq trace_msg_1
    cmp w0,#2
    b.eq trace_msg_2
    cmp w0,#3
    b.eq trace_msg_3
    cmp w0,#4
    b.eq trace_msg_4
    ret
trace_msg_1:
    adr x15,msg_1
    b trace_draw
trace_msg_2:
    adr x15,msg_2
    b trace_draw
trace_msg_3:
    adr x15,msg_3
    b trace_draw
trace_msg_4:
    adr x15,msg_4
    b trace_draw
trace_draw:
    movz w10,#0xf0ff
    movk w10,#0xffe6,lsl#16
    adr x17,font5_table
trace_char:
    ldrb w8,[x15],#1
    cbz w8,trace_done
    sub w8,w8,#32
    lsl x5,x8,#3
    sub x5,x5,x8
    add x5,x17,x5
    mov x2,x7
    movz x4,#7
trace_glyph_row:
    ldrb w11,[x5],#1
    mov x14,x2
    movz x6,#5
trace_glyph_bit:
    tbz w11,#4,trace_blank
    mov x9,x14
    movz x8,#4
trace_pixel_row:
    stp w10,w10,[x9]
    stp w10,w10,[x9,#8]
    add x9,x9,x3
    sub x8,x8,#1
    cbnz x8,trace_pixel_row
trace_blank:
    add x14,x14,#16
    lsl w11,w11,#1
    sub x6,x6,#1
    cbnz x6,trace_glyph_bit
    add x2,x2,x3,lsl#2
    sub x4,x4,#1
    cbnz x4,trace_glyph_row
    add x7,x7,#96
    b trace_char
trace_done:
    dsb sy
    ret


stack_snapshot:
    sub sp,sp,#192
    stp x19,x20,[sp,#96]
    stp x21,x22,[sp,#112]
    stp x23,x24,[sp,#128]
    stp x25,x26,[sp,#144]
    stp x27,x28,[sp,#160]
    stp x29,x30,[sp,#176]
    stp xzr,xzr,[sp,#32]
    stp xzr,xzr,[sp,#48]
    stp xzr,xzr,[sp,#64]
    stp xzr,xzr,[sp,#80]
    add x4,sp,#384
    str x4,[sp,#32]
    mrs x4,TCR_EL1
    movz x5,#0x251a
    movk x5,#0xa51a,lsl#16
    movk x5,#0x22,lsl#32
    cmp x4,x5
    b.eq stack_begin
    movz x4,#0x0101
    movk x4,#0x0101,lsl#16
    str x4,[sp,#88]
    b stack_print
stack_begin:
    mov x19,#1
stack_target:
    add x0,sp,#384
    cmp x19,#1
    b.ne stack_bottom
    sub x0,x0,#8
    b stack_capture
stack_bottom:
    cmp x19,#2
    b.ne stack_global
    sub x0,x0,#384
    b stack_capture
stack_global:
    movz x0,#0xabb8
    cmp x19,#3
    b.eq stack_global_high
    movz x0,#0xc048
stack_global_high:
    movk x0,#0x0716,lsl#16
    movk x0,#0xfff0,lsl#32
    movk x0,#0xffff,lsl#48
stack_capture:
    bl future_walk
    cmp x19,#1
    b.ne stack_store
    str x3,[sp,#80]
stack_store:
    mov x5,x4
    add x4,sp,#32
    str x0,[x4,x19,lsl#3]
    sub x6,x19,#1
    lsl x7,x6,#2
    lsl x2,x2,x7
    ldr x4,[sp,#72]
    orr x4,x4,x2
    add x7,x6,#16
    lsl x5,x5,x7
    orr x4,x4,x5
    str x4,[sp,#72]
    lsl x7,x6,#3
    lsl x1,x1,x7
    ldr x4,[sp,#88]
    orr x4,x4,x1
    str x4,[sp,#88]
    add x19,x19,#1
    cmp x19,#5
    b.ne stack_target
stack_print:
    mov x19,#1
stack_row:
    add x6,sp,#24
    ldr x4,[x6,x19,lsl#3]
    adr x5,stack_labels
    sub x6,x19,#1
    ldrb w5,[x5,x6]
    strb w5,[sp]
    mov w5,#32
    strb w5,[sp,#1]
    add x6,sp,#2
    mov x5,#16
    adr x14,stack_digits
stack_hex:
    lsr x8,x4,#60
    ldrb w8,[x14,x8]
    strb w8,[x6],#1
    lsl x4,x4,#4
    subs x5,x5,#1
    b.ne stack_hex
    strb wzr,[x6]
    movz x7,#0x0400,lsl#16
    movk x7,#0xfff0,lsl#32
    movk x7,#0xffff,lsl#48
    mov x3,#6400
    mov x9,#34
    mul x9,x19,x9
    add x9,x9,#10
    madd x7,x9,x3,x7
    add x7,x7,#2600
    mov x15,sp
    bl trace_draw
    add x19,x19,#1
    cmp x19,#9
    b.ne stack_row
    ldp x19,x20,[sp,#96]
    ldp x21,x22,[sp,#112]
    ldp x23,x24,[sp,#128]
    ldp x25,x26,[sp,#144]
    ldp x27,x28,[sp,#160]
    ldp x29,x30,[sp,#176]
    add sp,sp,#192
    ret
// x0=VA -> raw terminal descriptor, status, level, root PA, ancestor RO.
// x19 is the caller's loop counter; x20..x28 are saved by snapshot.
future_walk:
    mov x28,x30
    mov x21,x0
    mov x22,#1
    mov x27,#0
    mov x23,#0
    lsr x4,x0,#38
    cbz x4,walk_lower
    asr x4,x0,#38
    cmn x4,#1
    b.ne walk_bad_va
    mov x6,#16
    b walk_roots
walk_lower:
    mov x6,#0
walk_roots:
    movz x23,#0xaba0
    movk x23,#0x0716,lsl#16
    movk x23,#0xfff0,lsl#32
    movk x23,#0xffff,lsl#48
    ldr x20,[x23,#8]
    ldr x5,[x23,#24]
    cbz x20,walk_bad_root
    cbz x5,walk_bad_root
    orr x4,x20,x5
    tst x4,#0xfff
    b.ne walk_bad_root
    lsr x4,x4,#40
    cbnz x4,walk_bad_root
    cmp x20,x5
    csel x20,x20,x5,lo
    add x23,x23,x6
    ldp x24,x27,[x23]
    mov x23,#0
    tst x24,#0xfff
    b.ne walk_bad_root
    asr x4,x24,#38
    cmn x4,#1
    b.ne walk_bad_root
walk_level:
    mov x4,#3
    sub x4,x4,x22
    mov x5,#9
    mul x4,x4,x5
    add x4,x4,#12
    lsrv x5,x21,x4
    cmp x22,#1
    mov x6,#0xff
    mov x7,#0x1ff
    csel x6,x6,x7,eq
    and x5,x5,x6
    ldr x25,[x24,x5,lsl#3]
    cmp x22,#3
    b.eq walk_done
    tbz x25,#0,walk_done
    tbz x25,#1,walk_done
    tbz x25,#62,walk_child
    orr x23,x23,#1
walk_child:
    and x0,x25,#0xfffffffff000
    cmp x0,x20
    b.lo walk_bad_bounds
    movz x26,#0xc000
    movk x26,#0x0716,lsl#16
    movk x26,#0xfff0,lsl#32
    movk x26,#0xffff,lsl#48
    ldr x4,[x26,#0x138]
    add x5,x0,#0x1000
    cmp x5,x4
    b.hi walk_bad_bounds
    ldr x4,[x26,#0x108]
    cmp x0,x4
    b.lo walk_bad_bounds
    sub x5,x5,x4
    ldr x4,[x26,#0x110]
    cmp x5,x4
    b.hi walk_bad_bounds
    movz x16,#0x8784
    movk x16,#0x073e,lsl#16
    movk x16,#0xfff0,lsl#32
    movk x16,#0xffff,lsl#48
    blr x16
    tst x0,#0xfff
    b.ne walk_bad_pointer
    asr x4,x0,#38
    cmn x4,#1
    b.ne walk_bad_pointer
    mov x24,x0
    add x22,x22,#1
    b walk_level
walk_done:
    mov x0,x25
    mov x1,#0
    b walk_return
walk_bad_va:
    mov x23,#0
    mov x1,#2
    b walk_failed
walk_bad_root:
    mov x23,#0
    mov x1,#3
    b walk_failed
walk_bad_bounds:
    mov x1,#4
    b walk_failed
walk_bad_pointer:
    mov x1,#5
walk_failed:
    mov x0,#0
walk_return:
    mov x2,x22
    mov x3,x27
    mov x4,x23
    br x28
stack_digits: .ascii "0123456789ABCDEF"
stack_labels: .ascii "BPQDMLRS"
.p2align 2
.p2align 2
font5_table:
.byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,31,0,0,0,0,0,0,0,0,4,4,1,1,2,4,8,16,16,14,17,19,21,25,17,14,4,12,4,4,4,4,14,14,17,1,2,4,8,31,30,1,1,14,1,1,30,2,6,10,18,31,2,2,31,16,16,30,1,1,30,14,16,16,30,17,17,14,31,1,2,4,8,8,8,14,17,17,14,17,17,14,14,17,17,15,1,1,14,0,4,4,0,4,4,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,16,8,4,2,4,8,16,14,17,1,2,4,0,4,0,0,0,0,0,0,0,14,17,17,31,17,17,17,30,17,17,30,17,17,30,15,16,16,16,16,16,15,30,17,17,17,17,17,30,31,16,16,30,16,16,31,31,16,16,30,16,16,16,15,16,16,23,17,17,15,17,17,17,31,17,17,17,31,4,4,4,4,4,31,7,2,2,2,18,18,12,17,18,20,24,20,18,17,16,16,16,16,16,16,31,17,27,21,21,17,17,17,17,25,21,19,17,17,17,14,17,17,17,17,17,14,30,17,17,30,16,16,16,14,17,17,17,21,18,13,30,17,17,30,20,18,17,15,16,16,14,1,1,30,31,4,4,4,4,4,4,17,17,17,17,17,17,14,17,17,17,17,17,10,4,17,17,17,21,21,21,10,17,17,10,4,10,17,17,17,17,10,4,4,4,4,31,1,2,4,8,16,31
msg_1: .asciz "9 VM ENTRY"
msg_2: .asciz "D VM TABLES"
msg_3: .asciz "F VM MAP READY"
msg_4: .asciz "G MAP AUDIT"
