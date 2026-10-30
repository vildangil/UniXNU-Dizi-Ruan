#!/usr/bin/env python3
"""Fail-closed, offline SM7435 SMP topology/boot-option preflight.

Does NOT issue PSCI CPU_ON, touch GICR MMIO or assert XNU SMP works.
Only verifies that the curated Parrot DT and XNU boot policy are coherent.
"""
from __future__ import annotations
import argparse,json,re,tomllib
from pathlib import Path

EXPECTED_MPIDR=tuple(i<<8 for i in range(8))
EXPECTED_COMMON='22a71774c8ebf8ca6f2816bf774ff05d6b96e828'

def analyze(root:Path)->dict:
    dt=(root/'dts/sm7435-smp.dtsi').read_text()
    with (root/'feeds.toml').open('rb') as f:feeds=tomllib.load(f)
    with (root/'board.toml').open('rb') as f:board=tomllib.load(f)
    with (root/'package/unixnu.toml').open('rb') as f:menu=tomllib.load(f)
    with (root/'config/dizi-unixnu.toml').open('rb') as f:config=tomllib.load(f)
    found=[]
    for i in range(8):
        regex=rf'cpu{i}:\s*cpu@([0-9a-fA-F]+)\s*\{{([^}}]*)\}}'
        m=re.search(regex,dt,re.S)
        if not m:raise ValueError(f'Missing CPU{i} node')
        body=m.group(2)
        reg=re.search(r'\breg\s*=\s*<\s*0\s+(0x[0-9a-fA-F]+)\s*>\s*;',body)
        typ=re.search(r'\bunixnu,cluster-type\s*=\s*"([EP])"\s*;',body)
        if not reg or not typ or 'enable-method = "psci"' not in body:
            raise ValueError(f'Invalid CPU{i} PSCI/MPIDR/performance topology')
        raw=int(reg.group(1),16)
        if raw!=EXPECTED_MPIDR[i] or int(m.group(1),16)!=raw:raise ValueError(f'Incorrect CPU{i} MPIDR')
        if typ.group(1)!=('E' if i<4 else 'P'):raise ValueError('Unexpected 4E/4P CPU grouping')
        found.append({'cpu':i,'mpidr':f'0x{raw:03X}','class':typ.group(1),
                      'xnu_phys_id':raw&0xffff,'old_aff0_only_result':raw&0xff})
    if len(re.findall(r'cpu\d+:\s*cpu@',dt))!=8:raise ValueError('Unexpected extra CPU nodes')
    if len({x['xnu_phys_id'] for x in found})!=8:raise ValueError('MPIDR physical IDs alias')
    if len({x['old_aff0_only_result'] for x in found})!=1:raise ValueError('Old Aff0 diagnostic assumption wrong')
    if 'method = "smc"' not in dt or 'arm,psci-1.0' not in dt:raise ValueError('Unexpected PSCI ABI')
    if not all(x in dt for x in ('0x17200000','0x17260000','0x20000','0x100000','19200000')):
        raise ValueError('GICv3 or timer descriptor changed')
    if board['board']['example'] is not True:raise ValueError('Do not enable native XNU prematurely')
    if board['payload']['kernel_args']!=['-v','cpus=1']:raise ValueError('Default CPU policy must remain single-core')
    sources=[x for x in feeds['source'] if x.get('kind')=='soc' and x.get('name')=='sm7435']
    if len(sources)!=1 or sources[0]['commit']!=EXPECTED_COMMON:
        raise ValueError('SM7435 common revision does not contain the audited Aff1 patch')
    for cfg in (menu,config):
        entries={x['id']:x for x in cfg['entry']}
        if 'cpus=1' not in entries['xnu-singlecpu']['args']:raise ValueError('Missing safe single-core profile')
        if 'cpus=2' not in entries['xnu-dualcore']['args']:raise ValueError('Missing explicit, manual 2-core profile')
        if 'cpus=1' in entries['xnu-normal']['args']:raise ValueError('Normal profile is incorrectly pinned to 1 CPU')
        if cfg['boot']['default']!='return':raise ValueError('Menu safe default changed')
    return {'soc':'Qualcomm SM7435 Parrot','physical_cpu_nodes':found,
            'cpu_count_from_dt':8,'cpu_classes_from_dt':'4E+4P',
            'psci':'SMC; v1.0 described by DT, runtime not independently checked',
            'gicd_pa':'0x17200000','gicr_pa':'0x17260000',
            'gicr_stride_bytes':0x20000,'timer_frequency_hz':19200000,
            'xnu_reset_mpidr_mask':hex(0xffff),
            'soc_source_pin':EXPECTED_COMMON,
            'default_boot_cpu_policy':'cpus=1',
            'optional_test_profile':'cpus=2, available in config; not enabled automatically',
            'hardware_secondary_cpu_on_tested':False,
            'hardware_secondary_reset_vector_tested':False,
            'psci_affinity_info_readbacks_tested':False,
            'gicr_sgi_ppi_irq_delivery_tested':False,
            'xnu_smp_qualified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.'))
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    report=analyze(a.root)
    encoded=json.dumps(report,indent=2)+'\n'
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(encoded)
    print(encoded)
