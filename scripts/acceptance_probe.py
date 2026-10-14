#!/usr/bin/env python3
"""Physical/OS Platform Acceptance Probe (`scripts/acceptance_probe.py`)."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from human2api.native import LiveGTKAtkApplicationHarness  # noqa: E402
from human2api.models import Workflow, WorkflowStep, AssertionSpec  # noqa: E402
from human2api.runner import WorkflowRunner  # noqa: E402


def run_linux_gtk_probe(output_dir: pathlib.Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    harness = LiveGTKAtkApplicationHarness()
    if not harness.start():
        (output_dir / "linux_atspi_receipt.json").write_text(
            json.dumps({"target": "linux-atspi", "status": "blocked", "reason": "GTK3/ATK/Xvnc unavailable"}, indent=2)
        )
        return 2
    try:
        adapter = harness.build_live_adapter()
        wf = Workflow(
            name="Linux GTK/ATK Live Acceptance Probe",
            target="linux-atspi",
            mode="write",
            allowedApps=[harness.app_name],
            steps=[
                WorkflowStep(
                    action="type",
                    selector='automationId="customer_entry"',
                    automationId="customer_entry",
                    role="textbox",
                    text="شركة المشرق - AlMashreq",
                    isWriteAction=True,
                ),
                WorkflowStep(
                    action="type",
                    selector='automationId="notes_entry"',
                    automationId="notes_entry",
                    role="textbox",
                    text="دفعة أولى #101",
                    isWriteAction=True,
                ),
                WorkflowStep(
                    action="click",
                    selector='automationId="save_button"',
                    automationId="save_button",
                    role="button",
                    isWriteAction=True,
                    idempotent=False,
                ),
            ],
            assertions=[
                AssertionSpec(
                    type="assert_value",
                    selector='automationId="status_label"',
                    expected="تم الحفظ: شركة المشرق - AlMashreq | دفعة أولى #101",
                    match="exact",
                )
            ],
        )
        runner = WorkflowRunner(desktop_adapter=adapter)
        rep = runner.run(wf, allow_write=True)
        receipt = rep.to_dict()
        (output_dir / "linux_atspi_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if rep.status == "passed" else 1
    finally:
        harness.stop()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("target", choices=["linux-atspi", "windows-uia", "macos-ax", "android-companion"])
    p.add_argument("--output-dir", default=".h2a/probes")
    args = p.parse_args()
    out_dir = pathlib.Path(args.output_dir)
    if args.target == "linux-atspi":
        return run_linux_gtk_probe(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "target": args.target,
        "status": "blocked",
        "reason": f"Target {args.target} requires physical {args.target} OS/device hardware.",
    }
    (out_dir / f"{args.target}_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
