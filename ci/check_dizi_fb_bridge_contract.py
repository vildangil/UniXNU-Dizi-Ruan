#!/usr/bin/env python3
"""Source-only fail-closed preflight for Dizi's FB-BRIDGE-B.

Uses photographed PRE-switch tables; NEVER claims effective post-TTBR access.
Does not issue PSCI, MMIO or modify a boot image.
"""
import argparse
import copy
import json
from pathlib import Path

OLD = 0x802F6E000
NEW = 0x804191000
ALIAS = 0xFFFFFFF004000000
GOP = 0xB8000000
DESC = 0x00600000B8000C0D
MAIR = 0x0C0804FF00BB44FF

def check(condition, message):
    if not condition:
        raise ValueError(message)

def value(v):
    return int(v, 0) if isinstance(v, str) else int(v)

def evidence(sw, lf, st):
    check(value(sw["tcr_el1"]) == 0x22A51A251A, "Unexpected TCR")
    check([sw[k] for k in ("ttbr1_va_bits", "ttbr1_granule_bytes", "physical_address_bits", "start_level")] == [38, 4096, 40, 1], "Unexpected TTBR1 geometry")
    check(value(sw["roots"]["old"]["base_pa"]) == OLD and value(sw["roots"]["new"]["base_pa"]) == NEW, "Different TTBR1 roots")
    fb = sw["targets"]["framebuffer"]
    check(value(fb["va"]) == ALIAS and fb["indices"] == {"L1":192, "L2":32, "L3":0}, "Unexpected high VA indices")
    check(value(fb["new_initial_entry_pa"]) == NEW + 192*8, "Wrong L1 entry address")
    check(lf["framebuffer_l2_absent"] is True and value(lf["snapshot"]["F"]) == 0 and value(lf["snapshot"]["S"]) == 0, "New FB alias is not known empty")
    check(value(lf["snapshot"]["N"]) == NEW and value(lf["snapshot"]["K"]) == 0x804193003, "New code table differs")
    for n in ("C","H","X","V"):
        p = lf["leaves"][n]
        check(all(p[k] is True for k in ("valid_L3_page", "el1_execution_allowed_by_leaf", "matches_reference_page", "privileged_read_only")), "Unverified future code/vector page: " + n)
    check(value(st["selected_stack_root_pa"]) == NEW, "Different future stack root")
    for n in ("P","Q","D","M"):
        p = st["targets"][n]
        check(p["status"] == 0 and p["terminal_level"] == 3, "Incomplete future stack/global walk: " + n)
        check(all(p[k] is True for k in ("readback","valid_terminal_descriptor","writable_by_descriptor_and_ancestor_ap","kernel_only_writable_evidence","physical_address_fits_40bit")), "Future stack/data mapping not EL1 writable: " + n)
        check(st["bootstrap_reference_comparison"][n]["matches_reference"] is True, "Different reference PA: " + n)
    check(st["same_physical_backing_as_current_stack_verified"] is False and st["effective_post_switch_access_verified"] is False, "Do not overclaim effective future access")
    check(value(st["native_sp"]) in range(0xFFFFFFF007BB0000, 0xFFFFFFF007BB4000), "SP outside photographed intstack")
    check(DESC & 3 == 1 and ((DESC >> 2) & 7) == 3 and ((MAIR >> 24) & 0xff) == 0, "FB descriptor must select Device-nGnRnE")
    check(((DESC >> 6)&3) == 0 and ((DESC >> 10)&1) and ((DESC >> 11)&1) and ((DESC >> 53)&3) == 3, "FB must be EL1 RW AF nG UXN PXN")
    check((DESC & 0x0000FFFFFFE00000) == GOP and GOP % (2*1024*1024) == 0 and (2*1024*1024) <= 43*1024*1024, "FB output PA/length invalid")
    return {"pre_switch_table_evidence_pass":True, "expected_new_l2_entry_pa":"0x804192100", "expected_descriptor":hex(DESC),
            "MAIR_AttrIdx3":"0x00", "verified_effective_post_switch_access":False,
            "independent_old_new_stack_backing_comparison":False}

def source_contract(asm, patch):
    body = " ".join(line.split("//")[0].strip() for line in asm.splitlines())
    store = "str x5,[x19,#0x100]"
    check(body.count(store) == 1, "Expected exactly one new-L2 descriptor write")
    idx = body.index(store)
    for guard in ("mrs x4,TCR_EL1", "mrs x4,MAIR_EL1", "mrs x4,SCTLR_EL1",
                  "mrs x4,TTBR1_EL1", "ldp x6,x7,[x8]",
                  "ldr x4,[x19,#0x100]", "ldr x4,[x19,#0x1c8]", "ldr x4,[x0,#0x100]"):
        check(guard in body and body.index(guard) < idx, "Missing pre-store check: "+guard)
    check(body.count("dsb ishst") == 1 and idx < body.index("dsb ishst") < body.index("ldr x4,[x19,#0x100]",idx), "Missing DSB/readback after descriptor store")
    check("fb_refuse_loop:" in body and "fb_after_refuse_loop:" in body and body.count("wfe") == 2, "Fail-closed WFE exits absent")
    post = body.index("fb_after_switch:")
    check(post < body.index("mrs x2,TTBR1_EL1") < body.index("mrs x2,SCTLR_EL1") < body.index("bl fb_print",post), "Post-TTBR output not guarded by root/MMU checks")
    check("smc" not in body.lower() and "cpu_on" not in body.lower(), "No PSCI CPU_ON permitted")
    for t in ("HOOK_PRE_ADRP","HOOK_PRE_RETURN","HOOK_POST_ADRP","HOOK_POST_RETURN"):
        check(".inst "+t in asm, "Original ADRP / branch replay absent: "+t)
    for t in ("PRE=0xfffffff0073ea0b0","POST=0xfffffff0073ea130","EXPECTED_MMU=",
              "OUTPUT_BOOT=","TRACE_SHA=","'hardware_tested':False"):
        check(t in patch, "Pinned patcher contract changed: "+t)
    check(all(t in asm for t in ("#0x0c0d","#0xb800","#0x0060")), "Wrong framebuffer Device descriptor constructor")
    return {"one_L2_write_after_guards":True,"DSB_readback":True,"fail_closed":True,
            "post_TTBR_and_SCTLR_checked_before_write":True,"PSCI_CPU_ON":False}

def read_all(root):
    names = ("data/dizi-switch-b-root-decode-20261031.json",
             "data/dizi-leaf-b-pte-decode-20261031.json",
             "data/dizi-stack-b-hardware-decode-20261031.json")
    sw, lf, st = [json.loads((root/n).read_text()) for n in names]
    return sw, lf, st, (root/"ci/dizi_mmu_fb_bridge_b.S.in").read_text(), (root/"ci/patch_dizi_mmu_fb_bridge_b.py").read_text()

def negative_tests(sw, lf, st, asm, patch):
    changed = copy.deepcopy(lf)
    changed["snapshot"]["F"] = "0x1"
    for kwargs in ((sw,changed,st,asm,patch),):
        try: evidence(*kwargs[:3])
        except ValueError: pass
        else: raise AssertionError("Occupied future FB slot accepted")
    changed = copy.deepcopy(st)
    changed["targets"]["P"]["writable_by_descriptor_and_ancestor_ap"] = False
    try: evidence(sw,lf,changed)
    except ValueError: pass
    else: raise AssertionError("Read-only future SP accepted")
    for defective in (asm.replace("str x5,[x19,#0x100]","nop",1),
                      asm.replace("dsb ishst","nop",1)):
        try: source_contract(defective,patch)
        except ValueError: pass
        else: raise AssertionError("Unsafe missing store/barrier accepted")
    return 4

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,default=Path("."))
    ap.add_argument("--output",type=Path)
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    sw,lf,st,asm,patch=read_all(args.root)
    result={**evidence(sw,lf,st),**source_contract(asm,patch)}
    if args.self_test: result["negative_tests_passed"]=negative_tests(sw,lf,st,asm,patch)
    result["limitation"]="SOURCE/PRE-SWITCH AUDIT ONLY. Post-switch alias, active SP and XNU framebuffer driver not hardware verified."
    report=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(report)
    print(report)

if __name__=="__main__":
    main()
