#!/usr/bin/env python3
"""Render the student copies of each scenario, for eyeballing.

The role generates these at import time and never writes them to disk.
This does the same transform offline so you can read what the student
actually receives, diff it against `solutions`, or POST it at a live AO
yourself.

    python3 tests/render_student_variants.py            # summary
    python3 tests/render_student_variants.py --write DIR # write the JSON

Requires PyYAML. No network, no AO.
"""

import argparse
import json
import os
import sys

ROLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION_DIR = os.path.dirname(os.path.dirname(ROLE_DIR))
sys.path.insert(0, os.path.join(COLLECTION_DIR, "plugins", "filter"))

import yaml  # noqa: E402

from ao_workflow import (  # noqa: E402
    ao_prepare_definition,
    ao_student_variant,
)

# key -> (export filename, workflow name)
WORKFLOWS = {
    "disk_utilization": (
        "disk-utilization-remediation.json", "Disk Utilization Remediation"),
    "rhel_cve_remediation": (
        "rhel-cve-remediation.json", "RHEL CVE Remediation"),
    "ticket_enrichment": (
        "ticket-enrichment.json", "Ticket Enrichment Demo"),
}


def load_gaps():
    with open(os.path.join(ROLE_DIR, "files", "student_gaps.yml")) as handle:
        return yaml.safe_load(handle)["ao_student_gaps"]


def build(key):
    filename, name = WORKFLOWS[key]
    path = os.path.join(ROLE_DIR, "files", "workflows", filename)
    with open(path) as handle:
        full = ao_prepare_definition(json.load(handle), name)
    return name, full, ao_student_variant(full, load_gaps()[key])


def describe(name, full, student, gap):
    print("=" * 72)
    print(name)
    print("  gap: %s" % " ".join((gap.get("summary") or "?").split()))
    print("  solutions: %2d nodes / %2d edges"
          % (len(full["nodes"]), len(full["edges"])))
    print("  student  : %2d nodes / %2d edges"
          % (len(student["nodes"]), len(student["edges"])))

    for switch in [n for n in student["nodes"] if n["type"] == "switch"]:
        params = switch["parameters"]
        wired = {
            e.get("from_port"): e["to"] for e in student["edges"]
            if e.get("from") == switch["id"]
        }
        # A port is only the student's work if solutions wires it and
        # this copy does not. Several default ports are unwired in both
        # — that is the shipped design, not an exercise.
        solutions_wired = {
            e.get("from_port") for e in full["edges"]
            if e.get("from") == switch["id"]
        }
        print("  switch %s:" % (switch.get("name") or switch["id"]))
        rows = [(c["port"], c["label"], c.get("condition", ""))
                for c in params.get("cases", [])]
        rows.append((params.get("default_port"), "(default)", None))
        for port, label, condition in rows:
            target = wired.get(port)
            if target:
                edge = "-> %s" % target
            elif port in solutions_wired:
                edge = "-> EMPTY  <<< student builds this"
            else:
                edge = "-> (unwired in solutions too — by design)"
            print("    %-9s %-26s %s" % (port, label, edge))
            if condition is not None:
                shown = condition or "BLANK  <<< student fills this"
                print("    %-9s %-26s   condition: %s" % ("", "", shown))

    for node in student["nodes"]:
        if node["type"] == "agentic":
            params = node["parameters"]
            print("  agent %-24s strategy=%s tools=%d"
                  % (node["id"], params.get("tool_selection_strategy"),
                     len(params.get("tool_selections") or [])))

    for trigger in student.get("triggers", []):
        # Only webhook and EDA triggers require an authorized service
        # account. Reporting one as missing on a manual trigger invents
        # an exercise that does not exist.
        needs_sa = trigger["type"] in ("webhook_trigger", "eda_trigger")
        if not needs_sa:
            print("  trigger %-22s type=%s" % (trigger["id"][:20], trigger["type"]))
            continue
        has_sa = "authorized_service_account_ids" in trigger["parameters"]
        print("  trigger %-22s type=%s service account: %s"
              % (trigger["id"][:20], trigger["type"],
                 "present" if has_sa
                 else "ABSENT  <<< student attaches aap-student-webhooks"))

    dropped = {n["id"] for n in full["nodes"]} - {
        n["id"] for n in student["nodes"]}
    if dropped:
        names = {n["id"]: n.get("name") for n in full["nodes"]}
        print("  dropped: %s" % ", ".join(sorted(names[i] for i in dropped)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", metavar="DIR",
                        help="also write each student definition as JSON")
    args = parser.parse_args()

    gaps = load_gaps()
    for key in WORKFLOWS:
        name, full, student = build(key)
        describe(name, full, student, gaps[key])
        if args.write:
            os.makedirs(args.write, exist_ok=True)
            out = os.path.join(args.write, "%s.json" % key)
            with open(out, "w") as handle:
                json.dump(student, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            print("  written: %s" % out)


if __name__ == "__main__":
    main()
