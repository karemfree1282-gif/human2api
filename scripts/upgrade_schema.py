#!/usr/bin/env python3
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from human2api.models import Workflow
for p in (pathlib.Path(__file__).resolve().parents[1] / "src" / "human2api" / "examples").glob("*.json"):
    wf = Workflow.load(p)
    wf.save(p)
print("Upgraded all workflow examples to schemaVersion 0.5.")
