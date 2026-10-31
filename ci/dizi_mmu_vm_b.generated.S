.section .text.trace,"ax",%progbits
.p2align 2
trace_hit_1:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_1
 movz w13,#1
 b trace_common
trace_resume_1:
 ldp x12,x13,[sp],#16
 .inst 0xaa0003f3
 .inst 0x14170704
trace_hit_2:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_2
 movz w13,#2
 b trace_common
trace_resume_2:
 ldp x12,x13,[sp],#16
 .inst 0x91000108
 .inst 0x14170706
trace_hit_3:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_3
 movz w13,#3
 b trace_common
trace_resume_3:
 ldp x12,x13,[sp],#16
 .inst 0xaa1403e0
 .inst 0x1417084e
trace_hit_4:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_4
 movz w13,#4
 b trace_common
trace_resume_4:
 ldp x12,x13,[sp],#16
 .inst 0xaa1303e0
 .inst 0x1417084f
trace_hit_5:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_5
 movz w13,#5
 b trace_common
trace_resume_5:
 ldp x12,x13,[sp],#16
 .inst 0xaa1403e1
 .inst 0x1417084b
trace_hit_6:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_6
 movz w13,#6
 b trace_common
trace_resume_6:
 ldp x12,x13,[sp],#16
 .inst 0x52800020
 .inst 0x1417084a
trace_hit_7:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_7
 movz w13,#7
 b trace_common
trace_resume_7:
 ldp x12,x13,[sp],#16
 .inst 0x79000268
 .inst 0x1417086f
trace_hit_8:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_8
 movz w13,#8
 b trace_common
trace_resume_8:
 ldp x12,x13,[sp],#16
 .inst 0xaa0003f4
 .inst 0x14170879
trace_hit_9:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_9
 movz w13,#9
 b trace_common
trace_resume_9:
 ldp x12,x13,[sp],#16
 .inst 0xaa0103fa
 .inst 0x17ffdf3a
trace_hit_10:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_10
 movz w13,#10
 b trace_common
trace_resume_10:
 ldp x12,x13,[sp],#16
 .inst 0xf0ffebc9
 .inst 0x17ffdf4d
trace_hit_11:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_11
 movz w13,#11
 b trace_common
trace_resume_11:
 ldp x12,x13,[sp],#16
 .inst 0xf0ffebd3
 .inst 0x17ffdf5b
trace_hit_12:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_12
 movz w13,#12
 b trace_common
trace_resume_12:
 ldp x12,x13,[sp],#16
 .inst 0x92407415
 .inst 0x17ffdf57
trace_hit_13:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_13
 movz w13,#13
 b trace_common
trace_resume_13:
 ldp x12,x13,[sp],#16
 .inst 0xf0ffebc8
 .inst 0x17ffdfa5
trace_hit_14:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_14
 movz w13,#14
 b trace_common
trace_resume_14:
 ldp x12,x13,[sp],#16
 .inst 0xf0ffebd3
 .inst 0x17ffe0d5
trace_hit_15:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_15
 movz w13,#15
 b trace_common
trace_resume_15:
 ldp x12,x13,[sp],#16
 .inst 0xf9400108
 .inst 0x17ffe1da
trace_hit_16:
 stp x12,x13,[sp,#-16]!
 adr x12,trace_resume_16
 movz w13,#16
 b trace_common
trace_resume_16:
 ldp x12,x13,[sp],#16
 .inst 0x9240bd00
 .inst 0x17ffe1d4
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
    movz x10,#2600
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
    cmp w0,#5
    b.eq trace_msg_5
    cmp w0,#6
    b.eq trace_msg_6
    cmp w0,#7
    b.eq trace_msg_7
    cmp w0,#8
    b.eq trace_msg_8
    cmp w0,#9
    b.eq trace_msg_9
    cmp w0,#10
    b.eq trace_msg_10
    cmp w0,#11
    b.eq trace_msg_11
    cmp w0,#12
    b.eq trace_msg_12
    cmp w0,#13
    b.eq trace_msg_13
    cmp w0,#14
    b.eq trace_msg_14
    cmp w0,#15
    b.eq trace_msg_15
    cmp w0,#16
    b.eq trace_msg_16
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
trace_msg_5:
    adr x15,msg_5
    b trace_draw
trace_msg_6:
    adr x15,msg_6
    b trace_draw
trace_msg_7:
    adr x15,msg_7
    b trace_draw
trace_msg_8:
    adr x15,msg_8
    b trace_draw
trace_msg_9:
    adr x15,msg_9
    b trace_draw
trace_msg_10:
    adr x15,msg_10
    b trace_draw
trace_msg_11:
    adr x15,msg_11
    b trace_draw
trace_msg_12:
    adr x15,msg_12
    b trace_draw
trace_msg_13:
    adr x15,msg_13
    b trace_draw
trace_msg_14:
    adr x15,msg_14
    b trace_draw
trace_msg_15:
    adr x15,msg_15
    b trace_draw
trace_msg_16:
    adr x15,msg_16
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

.p2align 2
font5_table:
.byte 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,31,0,0,0,0,0,0,0,0,4,4,1,1,2,4,8,16,16,14,17,19,21,25,17,14,4,12,4,4,4,4,14,14,17,1,2,4,8,31,30,1,1,14,1,1,30,2,6,10,18,31,2,2,31,16,16,30,1,1,30,14,16,16,30,17,17,14,31,1,2,4,8,8,8,14,17,17,14,17,17,14,14,17,17,15,1,1,14,0,4,4,0,4,4,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,16,8,4,2,4,8,16,14,17,1,2,4,0,4,0,0,0,0,0,0,0,14,17,17,31,17,17,17,30,17,17,30,17,17,30,15,16,16,16,16,16,15,30,17,17,17,17,17,30,31,16,16,30,16,16,31,31,16,16,30,16,16,16,15,16,16,23,17,17,15,17,17,17,31,17,17,17,31,4,4,4,4,4,31,7,2,2,2,18,18,12,17,18,20,24,20,18,17,16,16,16,16,16,16,31,17,27,21,21,17,17,17,17,25,21,19,17,17,17,14,17,17,17,17,17,14,30,17,17,30,16,16,16,14,17,17,17,21,18,13,30,17,17,30,20,18,17,15,16,16,14,1,1,30,31,4,4,4,4,4,4,17,17,17,17,17,17,14,17,17,17,17,17,10,4,17,17,17,21,21,21,10,17,17,10,4,10,17,17,17,17,10,4,4,4,4,31,1,2,4,8,16,31
msg_1: .asciz "1 PROLOGUE"
msg_2: .asciz "2 TBI RETURN"
msg_3: .asciz "3 KC REBASE"
msg_4: .asciz "4 CPU DATA"
msg_5: .asciz "5 PE PLATFORM"
msg_6: .asciz "6 TIMER WFE"
msg_7: .asciz "7 CPU TOPO"
msg_8: .asciz "8 THREAD READY"
msg_9: .asciz "9 VM ENTRY"
msg_10: .asciz "A VM RAM"
msg_11: .asciz "B VM PHYSMAP"
msg_12: .asciz "C VM ENTROPY"
msg_13: .asciz "D VM TABLES"
msg_14: .asciz "E VM SEGMENTS"
msg_15: .asciz "F VM MAP READY"
msg_16: .asciz "G VM SWITCH"
