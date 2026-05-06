from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Iterable


def export_rows_to_csv(rows: Iterable[dict[str, object]]) -> str:
    materialized = [dict(row) for row in rows]
    if not materialized:
        return ""

    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in materialized:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return buffer.getvalue()


def export_rows_to_json(rows: Iterable[dict[str, object]]) -> str:
    return json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2)
