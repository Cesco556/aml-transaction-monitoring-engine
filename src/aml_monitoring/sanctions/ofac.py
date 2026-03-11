"""OFAC SDN list parser.

Parses the publicly available OFAC Specially Designated Nationals (SDN) CSV
format into :class:`SanctionsEntry` objects.
"""

from __future__ import annotations

import csv
from pathlib import Path

from aml_monitoring.sanctions.lists import SanctionsEntry

# Default download URL (placeholder — do not auto-download)
OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"


def parse_sdn_csv(filepath: str | Path) -> list[SanctionsEntry]:
    """Parse an OFAC SDN CSV file and return a list of :class:`SanctionsEntry`.

    The OFAC SDN CSV has these columns (no header row in the official file):
        ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign,
        Vessel_Type, Tonnage, GRT, Vessel_Flag, Vessel_Owner, Remarks

    For our sample/mock files we also support a header row with column names:
        ent_num, sdn_name, sdn_type, program, title, remarks, country, aliases

    This parser auto-detects whether a header row is present.
    """
    filepath = Path(filepath)
    entries: list[SanctionsEntry] = []

    with open(filepath, newline="", encoding="utf-8") as fh:
        # Peek at the first row to detect header presence
        sample = fh.read(4096)
        fh.seek(0)
        sniffer = csv.Sniffer()
        has_header = False
        try:
            has_header = sniffer.has_header(sample)
        except csv.Error:
            pass

        # Also check if first cell looks like a number (official OFAC = no header)
        first_cell = sample.split(",")[0].strip().strip('"')
        if first_cell.isdigit():
            has_header = False

        if has_header:
            reader = csv.DictReader(fh)
            for row in reader:
                r = {k.strip().lower(): v.strip() for k, v in row.items()}
                aliases_raw = r.get("aliases", "")
                aliases = [a.strip() for a in aliases_raw.split("|") if a.strip()]
                sdn_type = r.get("sdn_type", "individual").lower()
                entity_type = "organization" if sdn_type in ("entity", "organization") else "individual"
                entries.append(
                    SanctionsEntry(
                        name=r.get("sdn_name", r.get("name", "")),
                        aliases=aliases,
                        entity_type=entity_type,
                        source="OFAC",
                        country=r.get("country", ""),
                        list_date=r.get("list_date", ""),
                        extra={
                            "ent_num": r.get("ent_num", ""),
                            "program": r.get("program", ""),
                            "title": r.get("title", ""),
                            "remarks": r.get("remarks", ""),
                        },
                    )
                )
        else:
            # Official OFAC format: no header, positional columns
            reader_raw = csv.reader(fh)
            for row in reader_raw:
                if not row or len(row) < 2:
                    continue
                ent_num = row[0].strip().strip('"')
                sdn_name = row[1].strip().strip('"') if len(row) > 1 else ""
                sdn_type = row[2].strip().strip('"').lower() if len(row) > 2 else ""
                program = row[3].strip().strip('"') if len(row) > 3 else ""
                title = row[4].strip().strip('"') if len(row) > 4 else ""
                remarks = row[11].strip().strip('"') if len(row) > 11 else ""

                entity_type = "organization" if sdn_type in ("entity", "organization", "-0-") else "individual"
                entries.append(
                    SanctionsEntry(
                        name=sdn_name,
                        aliases=[],
                        entity_type=entity_type,
                        source="OFAC",
                        country="",
                        list_date="",
                        extra={
                            "ent_num": ent_num,
                            "program": program,
                            "title": title,
                            "remarks": remarks,
                        },
                    )
                )

    return entries
