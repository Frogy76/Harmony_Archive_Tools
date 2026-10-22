# Harmony Archive Tools

Command-line tools for working with the
[Harmony IR archive](https://github.com/harmonic-afterglow/harmony-ir-archive),
a snapshot of the Logitech Harmony cloud database of IR codes.

- `harmony_devices.py` – browse manufacturers, device types and devices, show the commands of a device
- `harmony_wig.py` – create a HAIR wig file (`*.wig.json`) from a device in the archive

Both scripts use the Python standard library only.

## Requirement: the Harmony IR archive

The tools do not contain any IR data themselves. They read the static API of the
archive at **https://github.com/harmonic-afterglow/harmony-ir-archive**, which must be
placed at **`/config/harmony-ir-archive`**:

```sh
git clone https://github.com/harmonic-afterglow/harmony-ir-archive /config/harmony-ir-archive
```

The tools then read `/config/harmony-ir-archive/docs/api/v1` (it must contain
`manifest.json`). Without the archive in this location the tools will not work,
unless you point them to another location with `--archive PATH` or the
`HARMONY_ARCHIVE` environment variable (both pointing to the `docs/api/v1` directory).

`harmony_wig.py` additionally needs the HAIR integration installed at
`/config/custom_components/hair`; it writes wigs to `/config/hair/wigs/` by default.

## Usage

Find a device and its global Harmony device ID:

```sh
python3 -I harmony_devices.py manufacturers philips
python3 -I harmony_devices.py search philips bdp3300 --commands
python3 -I harmony_devices.py show ID
```

Create a wig from it:

```sh
python3 -I harmony_wig.py ID --list     # preview the selected commands
python3 -I harmony_wig.py ID            # write to /config/hair/wigs/
```

Run either script with `--help` for all options.
