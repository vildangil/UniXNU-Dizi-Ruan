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
    b.ne table_skip
    bl table_snapshot
table_skip:
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


table_snapshot:
    sub sp,sp,#128
    stp x19,x20,[sp,#96]
    stp x21,x30,[sp,#112]
    stp xzr,xzr,[sp,#32]
    stp xzr,xzr,[sp,#48]
    stp xzr,xzr,[sp,#64]
    stp xzr,xzr,[sp,#80]
    movz x19,#0xabb0
    movk x19,#0x0716,lsl#16
    movk x19,#0xfff0,lsl#32
    movk x19,#0xffff,lsl#48
    ldr x20,[x19,#8]
    str x20,[sp,#32]
    mrs x4,TCR_EL1
    movz x5,#0x251a
    movk x5,#0xa51a,lsl#16
    movk x5,#0x22,lsl#32
    mov x21,#1
    cmp x4,x5
    b.ne table_result
    ldr x19,[x19]
    mov x21,#2
    tst x19,#0xfff
    b.ne table_result
    asr x5,x19,#38
    cmn x5,#1
    b.ne table_result
    ldr x4,[x19,#0x600]
    mov x21,#3
    and x5,x4,#3
    cmp x5,#3
    b.ne table_result
    and x19,x4,#0xfffffffff000
    mov x21,#4
    cmp x19,x20
    b.lo table_result
    movz x5,#0xc000
    movk x5,#0x0716,lsl#16
    movk x5,#0xfff0,lsl#32
    movk x5,#0xffff,lsl#48
    ldr x6,[x5,#0x138]
    add x7,x19,#0x1000
    cmp x7,x6
    b.hi table_result
    // Also bound the child to native gPhysBase / mem_size before phystokv.
    ldr x6,[x5,#0x108]
    cmp x19,x6
    b.lo table_result
    sub x7,x7,x6
    ldr x6,[x5,#0x110]
    cmp x7,x6
    b.hi table_result
    mov x0,x19
    movz x16,#0x8784
    movk x16,#0x073e,lsl#16
    movk x16,#0xfff0,lsl#32
    movk x16,#0xffff,lsl#48
    blr x16
    mov x21,#5
    tst x0,#0xfff
    b.ne table_result
    asr x5,x0,#38
    cmn x5,#1
    b.ne table_result
    ldr x4,[x0,#0x100]
    ldr x5,[x0,#0x1c8]
    stp x4,x5,[sp,#40]
    mov x21,#6
    and x6,x5,#3
    cmp x6,#3
    b.ne table_result
    and x19,x5,#0xfffffffff000
    mov x21,#7
    cmp x19,x20
    b.lo table_result
    movz x5,#0xc000
    movk x5,#0x0716,lsl#16
    movk x5,#0xfff0,lsl#32
    movk x5,#0xffff,lsl#48
    ldr x6,[x5,#0x138]
    add x7,x19,#0x1000
    cmp x7,x6
    b.hi table_result
    ldr x6,[x5,#0x108]
    cmp x19,x6
    b.lo table_result
    sub x7,x7,x6
    ldr x6,[x5,#0x110]
    cmp x7,x6
    b.hi table_result
    mov x0,x19
    movz x16,#0x8784
    movk x16,#0x073e,lsl#16
    movk x16,#0xfff0,lsl#32
    movk x16,#0xffff,lsl#48
    blr x16
    mov x21,#8
    tst x0,#0xfff
    b.ne table_result
    asr x5,x0,#38
    cmn x5,#1
    b.ne table_result
    ldr x4,[x0,#0xf50]
    ldr x5,[x0,#0xfb0]
    stp x4,x5,[sp,#56]
    ldr x4,[x0,#0xf88]
    ldr x5,[x0,#0xf68]
    stp x4,x5,[sp,#72]
    mov x21,#0
table_result:
    str x21,[sp,#88]
    mov x19,#1
table_row:
    add x6,sp,#24
    ldr x4,[x6,x19,lsl#3]
    adr x5,table_labels
    sub x6,x19,#1
    ldrb w5,[x5,x6]
    strb w5,[sp]
    mov w5,#32
    strb w5,[sp,#1]
    add x6,sp,#2
    mov x5,#16
    adr x14,table_digits
table_hex:
    lsr x8,x4,#60
    ldrb w8,[x14,x8]
    strb w8,[x6],#1
    lsl x4,x4,#4
    subs x5,x5,#1
    b.ne table_hex
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
    b.ne table_row
    ldp x19,x20,[sp,#96]
    ldp x21,x30,[sp,#112]
    add sp,sp,#128
    ret
table_digits: .ascii "0123456789ABCDEF"
table_labels: .ascii "NFKCHXVS"
.p2align 2
.p2align 2
font5_table:
.byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,31,0,0,0,0,0,0,0,0,4,4,1,1,2,4,8,16,16,14,17,19,21,25,17,14,4,12,4,4,4,4,14,14,17,1,2,4,8,31,30,1,1,14,1,1,30,2,6,10,18,31,2,2,31,16,16,30,1,1,30,14,16,16,30,17,17,14,31,1,2,4,8,8,8,14,17,17,14,17,17,14,14,17,17,15,1,1,14,0,4,4,0,4,4,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,16,8,4,2,4,8,16,14,17,1,2,4,0,4,0,0,0,0,0,0,0,14,17,17,31,17,17,17,30,17,17,30,17,17,30,15,16,16,16,16,16,15,30,17,17,17,17,17,30,31,16,16,30,16,16,31,31,16,16,30,16,16,16,15,16,16,23,17,17,15,17,17,17,31,17,17,17,31,4,4,4,4,4,31,7,2,2,2,18,18,12,17,18,20,24,20,18,17,16,16,16,16,16,16,31,17,27,21,21,17,17,17,17,25,21,19,17,17,17,14,17,17,17,17,17,14,30,17,17,30,16,16,16,14,17,17,17,21,18,13,30,17,17,30,20,18,17,15,16,16,14,1,1,30,31,4,4,4,4,4,4,17,17,17,17,17,17,14,17,17,17,17,17,10,4,17,17,17,21,21,21,10,17,17,10,4,10,17,17,17,17,10,4,4,4,4,31,1,2,4,8,16,31
msg_1: .asciz "9 VM ENTRY"
msg_2: .asciz "D VM TABLES"
msg_3: .asciz "F VM MAP READY"
msg_4: .asciz "G MAP AUDIT"
