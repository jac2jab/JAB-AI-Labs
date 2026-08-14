"""Scaffold a new vendor pack.

    python new_pack.py fortinet

Creates the twelve sections from the schema in packs.py, each containing the
question it exists to answer rather than an empty file. Never overwrites
content that already exists.
"""

import argparse
import json
import sys

from packs import (
    METADATA_FILE,
    PACKS_DIR,
    RESERVED_NAMES,
    SECTIONS,
    metadata_template,
    pack_status,
    section_template,
)


def create_pack(vendor: str) -> None:
    """Create or complete a vendor pack skeleton."""
    vendor = vendor.strip().lower().replace(" ", "-")

    if not vendor or not all(c.isalnum() or c in "-_" for c in vendor):
        raise ValueError(
            f"'{vendor}' is not a usable directory name. Use letters, numbers, "
            "hyphens, or underscores."
        )

    if vendor in RESERVED_NAMES:
        raise ValueError(
            f"'{vendor}' is reserved. It holds the vendor-agnostic SE playbook "
            "that loads alongside every pack, not a vendor's knowledge."
        )

    pack_dir = PACKS_DIR / vendor
    existed = pack_dir.is_dir()
    pack_dir.mkdir(parents=True, exist_ok=True)

    created, skipped = [], []

    metadata_path = pack_dir / METADATA_FILE
    if metadata_path.exists():
        skipped.append(METADATA_FILE)
    else:
        metadata_path.write_text(
            json.dumps(metadata_template(vendor), indent=2) + "\n", encoding="utf-8"
        )
        created.append(METADATA_FILE)

    for filename in SECTIONS:
        path = pack_dir / filename

        if path.exists():
            skipped.append(filename)
            continue

        path.write_text(section_template(filename), encoding="utf-8")
        created.append(filename)

    verb = "Completed" if existed else "Created"
    print(f"{verb} vendor pack: {pack_dir.relative_to(PACKS_DIR.parent)}")
    print(f"  {len(created)} file(s) created")

    if skipped:
        print(f"  {len(skipped)} left alone (already present)")

    status = pack_status(vendor)
    print(f"  {status['percent_complete']}% written "
          f"({len(status['written'])}/{status['total']} sections)")
    print()
    print("Start with demo_flows.md — it is the highest-value section and the")
    print("hardest for anyone else to reproduce.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new vendor pack.")
    parser.add_argument("vendor", help="Vendor name, e.g. fortinet")
    args = parser.parse_args()

    try:
        create_pack(args.vendor)
    except (ValueError, OSError) as error:
        print(f"Could not create pack: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
