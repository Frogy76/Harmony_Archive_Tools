#!/usr/bin/env python3
"""Create a HAIR wig file (*.wig.json) from a device in the Harmony IR archive.

    python3 -I harmony_wig.py ID                      # writes to /config/hair/wigs/
    python3 -I harmony_wig.py ID --list               # only show what would be included
    python3 -I harmony_wig.py ID --keys "PowerToggle,VolumeUp,VolumeDown"
    python3 -I harmony_wig.py ID --exclude "0,1,2,3,4,5,6,7,8,9"
    python3 -I harmony_wig.py ID --alias "PowerToggle=Power Toggle" --kind tv -o file.wig.json

The ID can be found with harmony_devices.py (search/show). The archive's Pronto hex is
taken over unchanged, only the first frame (`pronto`), without `prontoRepeat` – just like
the existing wigs in hair/wigs/. Commands without Pronto (IP control, not rendered)
are skipped and reported.

The file is written and validated with serialize_wig/parse_wig from custom_components/hair,
so that it matches the format of the installed HAIR version exactly.
"""
from __future__ import annotations

import argparse
import gzip
import importlib
import json
import os
import sys
import types
from datetime import date
from pathlib import Path

ARCHIVE = Path(os.environ.get("HARMONY_ARCHIVE", "/config/harmony-ir-archive/docs/api/v1"))
HAIR = Path("/config/custom_components/hair")
WIG_DIR = Path("/config/hair/wigs")

# Harmony device type (DeviceTypeDisplayName) → word from HAIR's KIND_LIST
KIND_FROM_TYPE = {
    "Television": "tv", "TVDVD": "tv", "TVVCR": "tv", "TVDVDVCR": "tv", "TVHDD": "tv",
    "Monitor": "monitor", "Projector": "projector",
    "DigitalSetTopBox": "settopbox", "Satellite": "settopbox", "CableBox": "settopbox",
    "PVR": "settopbox", "Roku": "settopbox", "AppleTV": "settopbox", "GoogleTV": "settopbox",
    "DVD": "player", "DVDRecorder": "player", "DVDVCR": "player", "DVDRVCR": "player",
    "VCR": "player", "CDPlayer": "player", "CDJukebox": "player", "LaserdiscPlayer": "player",
    "MinidiscPlayer": "player", "TapeDeck": "player", "DAT": "player", "MediaPlayer": "player",
    "DigitalMusicServer": "player", "MediaCenterPC": "player", "GameConsole": "player",
    "GameConsoleWithDvd": "player",
    "StereoReceiver": "receiver", "RadioTuner": "receiver", "Amplifier": "amplifier",
    "MiniSystemCDRadioCassette": "minisystem", "MiniSystemDvdCDRadio": "minisystem",
    "MiniSystemDvdVcrRadio": "minisystem",
    "AudioVideoSwitch": "avswitch", "TVCamera": "camera", "Camera": "camera",
    "ClimateControl": "ac", "Thermostat": "ac", "LightController": "light",
}


def load(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def device_and_commands(gid: int) -> tuple[dict, list[dict]]:
    manifest = json.loads((ARCHIVE / "manifest.json").read_text(encoding="utf-8"))
    g = load(ARCHIVE / "devices" / f"{gid % manifest['device_buckets']:03x}.json.gz").get(str(gid))
    if not g:
        sys.exit(f"Device {gid} not found in archive")
    codeset = g.get("codeset")
    cmds = []
    if codeset:
        bucket = load(ARCHIVE / "codesets" / f"{codeset[: manifest['codeset_prefix']]}.json.gz")
        cmds = bucket.get(codeset, [])
    return g, cmds


def hair_wig_format():
    """Load wig_format.py of the HAIR integration without importing its __init__ (Home Assistant)."""
    if not (HAIR / "wig_format.py").exists():
        return None
    package = types.ModuleType("hair")
    package.__path__ = [str(HAIR)]
    sys.modules["hair"] = package
    return importlib.import_module("hair.wig_format")


def split_list(text: str | None) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()] if text else []


def main():
    global ARCHIVE
    p = argparse.ArgumentParser(description="Create a HAIR wig from the Harmony IR archive")
    p.add_argument("id", type=int, help="global Harmony device ID (see harmony_devices.py)")
    p.add_argument("--archive", type=Path, help=f"path to docs/api/v1 (default {ARCHIVE})")
    p.add_argument("-o", "--output", type=Path, help=f"file or directory (default {WIG_DIR})")
    p.add_argument("--name", help="name of the wig (default: Harmony name, e.g. \"Philips BDP3300\")")
    p.add_argument("--kind", help="HAIR device kind (tv, receiver, player, settopbox …); default derived from the Harmony type")
    p.add_argument("--keys", help="only these commands, comma-separated, in this order")
    p.add_argument("--exclude", help="leave out these commands, comma-separated")
    p.add_argument("--alias", action="append", default=[], metavar="OLD=NEW",
                   help="rename a command, can be given multiple times")
    p.add_argument("--note", help="text appended to the notes")
    p.add_argument("--list", action="store_true", help="write nothing, only show the selection")
    p.add_argument("-f", "--force", action="store_true", help="overwrite an existing file")
    args = p.parse_args()
    if args.archive:
        ARCHIVE = args.archive

    g, cmds = device_and_commands(args.id)
    d = g["device"]
    dev_type = d.get("DeviceTypeDisplayName")
    with_pronto = {c["Name"]: c for c in cmds if c.get("pronto")}
    without_pronto = [c["Name"] for c in cmds if not c.get("pronto")]

    # Selection
    if args.keys:
        names = split_list(args.keys)
        missing = [n for n in names if n not in with_pronto]
        if missing:
            sys.exit(f"Not in codeset or without Pronto: {', '.join(missing)}\n"
                     f"Available: {', '.join(with_pronto)}")
    else:
        names = list(with_pronto)
    excluded = set(split_list(args.exclude))
    names = [n for n in names if n not in excluded]

    renames = {}
    for a in args.alias:
        old, _, new = a.partition("=")
        if not new or old.strip() not in with_pronto:
            sys.exit(f"--alias {a!r}: format OLD=NEW, OLD must be a command with Pronto")
        renames[old.strip()] = new.strip()

    signals, taken = [], set()
    for n in names:
        alias = renames.get(n, n)
        if alias in taken:
            sys.exit(f"Alias {alias!r} is duplicated – resolve with --alias or --exclude")
        taken.add(alias)
        signals.append((alias, with_pronto[n]["pronto"], n))

    if not signals:
        sys.exit("No commands with Pronto – no IR wig can be created for this device")

    kind = args.kind or KIND_FROM_TYPE.get(dev_type, "other")
    name = args.name or d.get("Name") or f"{d.get('Manufacturer')} {d.get('Model')}"

    print(f"{name}  (ID {args.id}, {dev_type} → kind {kind}, codeset {g.get('codeset')})", file=sys.stderr)
    print(f"  {len(signals)} of {len(cmds)} commands included", file=sys.stderr)
    if without_pronto:
        print(f"  skipped without Pronto: {', '.join(without_pronto)}", file=sys.stderr)
    if args.list:
        for alias, pronto, n in signals:
            print(f"  {alias}" + (f"  (from {n})" if alias != n else ""))
        return

    notes = (f"Pronto hex from the harmony-ir-archive (Logitech Harmony cloud, snapshot "
             f"{json.loads((ARCHIVE / 'manifest.json').read_text())['captured']}, CC0), "
             f"global device ID {args.id}; {len(signals)} keys, created on "
             f"{date.today():%Y-%m-%d} with harmony_wig.py. First frame only, without "
             f"repeat frame. Not verified on hardware.")
    if args.note:
        notes += " " + args.note

    wf = hair_wig_format()
    if wf is None:
        sys.exit(f"HAIR not found at {HAIR} – wig_format.py is required for writing")
    if kind not in wf.KIND_BY_KEY:
        sys.exit(f"kind {kind!r} unknown, allowed: {', '.join(wf.KIND_BY_KEY)}")
    wig = wf.Wig(
        name=name,
        signals=[wf.WigSignal(alias=a, pronto=pr) for a, pr, _ in signals],
        brand=d.get("Manufacturer"),
        model=d.get("Model"),
        kind=kind,
        notes=notes,
        origin="converted:harmony-ir-archive",
    )
    text = wf.serialize_wig(wig)

    check = wf.parse_wig(text)
    if not check.ok:
        sys.exit("parse_wig rejects the wig:\n  " + "\n  ".join(check.errors))

    target = args.output or WIG_DIR
    if target.is_dir() or not target.suffix:
        target = target / wf.wig_filename(name)
    if target.exists() and not args.force:
        sys.exit(f"{target} already exists – overwrite with --force or specify -o")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"  written: {target} (accepted by parse_wig)", file=sys.stderr)


if __name__ == "__main__":
    main()
