"""Operator-run, real-device probe bound to the current implementation digest.

Requires a reviewed workflow ending with at least one actual result assertion.
Use only synthetic test data in an owned test app. This writes an operator
receipt, not an independent hardware certification or proof of every feature.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from human2api.completion import source_digest, PLATFORMS
from human2api.models import load_workflow, WorkflowError
from human2api.runner import run_workflow


def probe(target: str, workflow: Path, data: Path, output: Path, acknowledge: bool) -> Path:
    if not acknowledge:
        raise WorkflowError('explicit --acknowledge-owned-test-app is required')
    expected={'windows-uia':'Windows','macos-ax':'Darwin','linux-atspi':'Linux'}
    if target in expected and platform.system()!=expected[target]:
        raise WorkflowError('must run the probe on the selected operating system')
    wf=load_workflow(workflow)
    if wf.get('target')!=('android' if target=='android-companion' else 'desktop'):
        raise WorkflowError('probe target differs from workflow target')
    if target=='android-companion' and not os.environ.get('H2A_ANDROID_BRIDGE_TOKEN'):
        raise WorkflowError('arm the companion explicitly before acceptance')
    assertions=sum(s['action'] in {'ui_assert_text','assert_text'} for s in wf['steps'])
    if not assertions or wf['steps'][-1]['action'] not in {'ui_assert_text','assert_text'}:
        raise WorkflowError('acceptance must end with a real UI text assertion')
    values=json.loads(data.read_text(encoding='utf-8'))
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    result=run_workflow(wf,values,approve_writes=True,artifacts_dir=output/'artifacts')
    receipt={'target':target,'status':'passed' if result.get('ok') else 'failed','simulated':False,
        'sourceDigest':source_digest(ROOT),'verificationAssertions':assertions,
        'workflowSha256':hashlib.sha256(workflow.read_bytes()).hexdigest(),
        'timestamp':int(time.time()),'os':platform.system(),'version':platform.release(),
        'note':'Operator execution receipt; not independent attestation. No inputs or result text persisted.'}
    path=output/(target+'.json')
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as out:json.dump(receipt,out,indent=2)
    return path


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('target',choices=PLATFORMS)
    p.add_argument('--workflow',required=True,type=Path)
    p.add_argument('--data-file',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--acknowledge-owned-test-app',action='store_true')
    a=p.parse_args()
    try:
        print(probe(a.target,a.workflow,a.data_file,a.output,a.acknowledge_owned_test_app))
    except (WorkflowError,ValueError,OSError) as exc:
        print(f'Acceptance failed: {exc}',file=sys.stderr);raise SystemExit(2)
