#!/usr/bin/env python3
"""Overview of the devices in the Harmony IR archive.

Reads the archive's static API (harmonic-afterglow/harmony-ir-archive,
directory docs/api/v1) – standard library only, runs via CLI:

    python3 -I harmony_devices.py manufacturers [PATTERN]
    python3 -I harmony_devices.py types
    python3 -I harmony_devices.py search TERM... [--manufacturer X] [--type Y] [--commands]
    python3 -I harmony_devices.py show ID [--pronto]
    python3 -I harmony_devices.py export FILE.csv

The ID is the global Harmony device ID; harmony_wig.py uses it to create the wig file.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

ARCHIVE = Path(os.environ.get("HARMONY_ARCHIVE", "/config/harmony-ir-archive/docs/api/v1"))

POWER_TYPE = {0: "unknown", 1: "discrete (on/off)", 2: "toggle", 3: "none"}


def load(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def manifest() -> dict:
    return load(ARCHIVE / "manifest.json")


@lru_cache(maxsize=None)
def manufacturer_list() -> list[dict]:
    return load(ARCHIVE / "manufacturers.json")


def catalog():
    """All devices as (manufacturer, entry) – from manufacturers/<slug>.json."""
    for m in manufacturer_list():
        for entry in load(ARCHIVE / "manufacturers" / f"{m['slug']}.json"):
            yield m["name"], entry


@lru_cache(maxsize=64)
def _device_bucket(nr: int) -> dict:
    return load(ARCHIVE / "devices" / f"{nr:03x}.json.gz")


@lru_cache(maxsize=256)
def _codeset_bucket(prefix: str) -> dict:
    return load(ARCHIVE / "codesets" / f"{prefix}.json.gz")


def device(gid: int) -> dict | None:
    return _device_bucket(gid % manifest()["device_buckets"]).get(str(gid))


def commands(codeset: str | None) -> list[dict]:
    if not codeset:
        return []
    return _codeset_bucket(codeset[: manifest()["codeset_prefix"]]).get(codeset, [])


def _norm(text: str) -> str:
    """Lowercase without spaces/punctuation: "AVR-X 2400H" matches "avrx2400h"."""
    return re.sub(r"[^0-9a-z]+", "", text.lower())


# ---------------------------------------------------------------- Subcommands

def cmd_manufacturers(args):
    pattern = _norm(args.pattern or "")
    result = [m for m in manufacturer_list() if pattern in _norm(m["name"])]
    result.sort(key=lambda m: (-m["devices"], m["name"].lower()) if args.by_count
                else m["name"].lower())
    for m in result:
        print(f"{m['devices']:7d}  {m['name']}")
    print(f"\n{len(result)} manufacturers, {sum(m['devices'] for m in result)} devices", file=sys.stderr)


def cmd_types(args):
    counter = Counter(e.get("type") for _, e in catalog())
    for dev_type, count in counter.most_common():
        print(f"{count:7d}  {dev_type}")


def cmd_search(args):
    terms = [_norm(t) for t in args.terms]
    manufacturer = _norm(args.manufacturer) if args.manufacturer else None
    dev_type = args.type.lower() if args.type else None
    hits = []
    for name, e in catalog():
        if manufacturer and manufacturer not in _norm(name):
            continue
        if dev_type and dev_type not in (e.get("type") or "").lower():
            continue
        text = _norm(f"{name} {e.get('model', '')} {e.get('name', '')}")
        if all(t in text for t in terms):
            hits.append((name, e))
    hits.sort(key=lambda h: (h[0].lower(), h[1].get("model", "").lower()))
    for name, e in hits[: args.limit]:
        extra = ""
        if args.commands:
            g = device(e["id"])
            cmds = commands(g.get("codeset")) if g else []
            extra = f"  {sum(1 for c in cmds if c.get('pronto')):3d}/{len(cmds):3d} IR"
        print(f"{e['id']:7d}  {name:<22.22} {e.get('model', ''):<28.28} {e.get('type', ''):<22}{extra}")
    rest = len(hits) - args.limit
    print(f"\n{len(hits)} hits" + (f" ({rest} more, increase --limit)" if rest > 0 else ""),
          file=sys.stderr)


def cmd_show(args):
    g = device(args.id)
    if not g:
        sys.exit(f"Device {args.id} not found in archive")
    d, f = g["device"], g.get("features", {})
    cmds = commands(g.get("codeset"))
    power = (f.get("PowerFeature") or [{}])[0]
    print(f"{d.get('Name')}  (ID {args.id})")
    print(f"  Manufacturer {d.get('Manufacturer')}")
    print(f"  Model        {d.get('Model')}")
    print(f"  Type         {d.get('DeviceTypeDisplayName')}")
    print(f"  Codeset      {g.get('codeset')}  ({len(cmds)} commands, "
          f"{sum(1 for c in cmds if c.get('pronto'))} with Pronto)")
    print(f"  Timing       InterKeyDelay {d.get('InterKeyDelay')} ms, "
          f"InterDeviceDelay {d.get('InterDeviceDelay')} ms, PressMinRepeats {d.get('PressMinRepeats')}")
    print(f"  Power        {POWER_TYPE.get(power.get('PowerTypeId'), power.get('PowerTypeId'))}, "
          f"PowerOnDelay {power.get('PowerOnDelay', 0)} ms")
    for field, title in (("PowerOnActions", "On"), ("PowerOffActions", "Off"),
                         ("PowerToggleActions", "Toggle")):
        if power.get(field):
            print(f"    {title:<7}{_actions(power[field])}")
    inputs = (f.get("InputFeature") or [{}])[0].get("Inputs") or []
    if inputs:
        print(f"  Inputs       {len(inputs)}")
        for i in sorted(inputs, key=lambda i: i.get("InputOrder", 0)):
            print(f"    {i.get('InputName', ''):<24} {_actions(i.get('Actions') or [])}")
    print("  Commands")
    for c in cmds:
        pronto = c.get("pronto")
        if args.pronto and pronto:
            print(f"    {c['Name']}\n      {pronto}")
        else:
            print(f"    {'IR ' if pronto else '-- '}{c['Name']:<28} {c.get('KeyCode', '')}")


def _actions(actions: list[dict]) -> str:
    parts = []
    for a in sorted(actions, key=lambda a: a.get("Order", 0)):
        kind = a.get("__type", "")
        if kind in ("IRPressAction", "IRHoldAction"):
            parts.append(a.get("IRCommandName", "?"))
        elif kind == "IRDelayAction":
            parts.append(f"[{a.get('Delay')} ms]")
        elif kind == "IRDevAction":
            parts.append(f"[{a.get('StateName')}={a.get('StateValue')}]")
    return " → ".join(parts)


def cmd_export(args):
    with open(args.file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "manufacturer", "model", "name", "type"])
        n = 0
        for name, e in catalog():
            w.writerow([e["id"], name, e.get("model", ""), e.get("name", ""), e.get("type", "")])
            n += 1
    print(f"{n} devices written to {args.file}", file=sys.stderr)


def main():
    global ARCHIVE
    p = argparse.ArgumentParser(description="Query devices in the Harmony IR archive")
    p.add_argument("--archive", type=Path, help=f"path to docs/api/v1 (default {ARCHIVE})")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("manufacturers", help="manufacturers with device count")
    s.add_argument("pattern", nargs="?")
    s.add_argument("-n", "--by-count", action="store_true", help="sort by device count")
    s.set_defaults(func=cmd_manufacturers)

    s = sub.add_parser("types", help="device types with count")
    s.set_defaults(func=cmd_types)

    s = sub.add_parser("search", help="search devices by manufacturer/model/name")
    s.add_argument("terms", nargs="*", help="all must match (case-insensitive, hyphens ignored)")
    s.add_argument("--manufacturer", "-m")
    s.add_argument("--type", "-t", help="substring of the type, e.g. television, receiver, dvd")
    s.add_argument("--limit", "-l", type=int, default=100)
    s.add_argument("--commands", "-c", action="store_true", help="show number of IR commands with Pronto (slower)")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("show", help="details and commands of a device")
    s.add_argument("id", type=int)
    s.add_argument("--pronto", "-p", action="store_true", help="print Pronto hex for each command")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("export", help="write the whole catalog as CSV (semicolon-separated)")
    s.add_argument("file")
    s.set_defaults(func=cmd_export)

    args = p.parse_args()
    if args.archive:
        ARCHIVE = args.archive
    if not (ARCHIVE / "manifest.json").exists():
        sys.exit(f"No archive at {ARCHIVE} (manifest.json missing)")
    args.func(args)


if __name__ == "__main__":
    main()
