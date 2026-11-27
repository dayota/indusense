"""Adapter les moteurs existants au chargement brut, sans exécuter le SQL reçu."""

import csv
import hashlib
import io
import json
import yaml
from collections import Counter
from pathlib import Path

from fastapi import HTTPException
from indusense_ingestion.contracts import UniqueKeyLoader, read_config, validate_configuration
from indusense_ingestion.ingestion import generate_identity, read_text_source
from indusense_ingestion.sql_ingestion import Unevaluated, generate_sql_identity
from indusense_ingestion.bronze import resolve_specs

MAX_FILES = 10
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_BODY_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = MAX_FILES * 200000 + 16384


def contract_paths(root):
    directory = (root / "config/contracts").resolve()
    return {
        path.stem: path
        for path in sorted(directory.glob("*.yaml"))
        if path.is_file() and path.resolve().parent == directory
    }


def receive(upload, directory, expected_digest=None):
    filename = upload.filename or ""
    if (
        not filename
        or len(filename) > 255
        or any(ord(c) < 32 for c in filename)
        or "/" in filename
        or "\\" in filename
    ):
        raise HTTPException(422, "Nom de fichier invalide")
    suffix = Path(filename).suffix.lower()
    if suffix not in (".csv", ".sql"):
        raise HTTPException(
            422, f"{filename} : seuls CSV et SQL PostgreSQL sont acceptés"
        )
    path = directory / ("source" + suffix)
    digest, size = hashlib.sha256(), 0
    with path.open("xb") as target:
        while chunk := upload.file.read(256 * 1024):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise HTTPException(413, f"{filename} : limite de 25 Mio par fichier")
            digest.update(chunk)
            target.write(chunk)
    if not size:
        raise HTTPException(422, f"{filename} : fichier vide")
    checksum = digest.hexdigest()
    if expected_digest is not None and checksum != expected_digest:
        raise HTTPException(
            422, f"{filename} : empreinte SHA-256 différente de celle annoncée"
        )
    return {
        "path": path,
        "filename": filename,
        "sha256": checksum,
        "size_bytes": size,
        "format": suffix[1:],
    }


def parse_csv_contract(text, types):
    contract = yaml.load(text, Loader=UniqueKeyLoader)
    validate_configuration(contract, types)
    try:
        json.dumps(contract, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("Le contrat doit contenir des valeurs simples et finies ; entourer les dates de guillemets") from None
    return contract


def raw_csv(source):
    text, _ = read_text_source(source)
    delimiter = csv.Sniffer().sniff(text[:65536], delimiters=",;\t").delimiter
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
    headers = next(reader)
    if not headers or len(headers) != len(set(headers)) or any(not name.strip() for name in headers):
        raise ValueError("En-têtes CSV vides ou dupliqués")
    rows = []
    for values in reader:
        if not values:
            values = [""] * len(headers)
        if len(values) != len(headers):
            raise ValueError("Nombre de champs CSV incohérent")
        rows.append(dict(zip(headers, values)))
    return headers, rows


def analyze(source, entry, root, work, *, csv_contract=None):
    types_path = root / "config/types.yaml"
    types = read_config(types_path)
    contract = None
    if source["format"] == "csv":
        if csv_contract is not None:
            contract = csv_contract
        elif entry.contract_yaml is not None:
            contract = parse_csv_contract(entry.contract_yaml, types["types"])
        else:
            selected = contract_paths(root).get(entry.contract)
            if selected is None:
                raise HTTPException(422, "Choisir un contrat CSV existant ou précharger pour en générer un")
            contract = read_config(selected)
        validate_configuration(contract, types["types"])
        selected = work / "contract.yaml"
        selected.write_text(yaml.safe_dump(contract, allow_unicode=True, sort_keys=False), encoding="utf-8")
        headers, raw_rows = raw_csv(source["path"])
        result = generate_identity(
            source["path"],
            "identity",
            contract_path=selected,
            types_path=types_path,
            root=work,
        )
        tables = {"data": raw_rows}
        table_summaries = [
            {
                "name": "data",
                "rows": len(raw_rows),
                "cols": len(headers),
                "columns": [
                    {"name": name, "type": result["columns"][name]["type"]}
                    for name in headers
                ],
            }
        ]
    else:
        if entry.contract is not None or entry.contract_yaml is not None or entry.contract_mode != "existing":
            raise HTTPException(
                422, "Le SQL utilise son schéma CREATE TABLE, sans contrat CSV"
            )
        result = generate_sql_identity(
            source["path"], "identity", root=work, types_path=types_path
        )
        tables, table_summaries = {}, []
        for name, table in result["tables"].items():
            tables[name] = [
                {
                    key: {"sql_expression": value.sql}
                    if isinstance(value, Unevaluated)
                    else value
                    for key, value in row.items()
                }
                for row in table["rows"]
            ]
            table_summaries.append(
                {
                    "name": name,
                    "rows": len(table["rows"]),
                    "cols": len(table["schema"]),
                    "columns": [
                        {"name": col, "type": spec["type"]}
                        for col, spec in table["schema"].items()
                    ],
                }
            )
    notes = list(result["notes"])
    table_specs = {}
    for table in table_summaries:
        if source["format"] == "csv":
            table_specs[table["name"]] = resolve_specs(contract, table["columns"])
        else:
            table_specs[table["name"]] = [
                {"name": name, "spec": {"type": spec["type"], "nullable": spec["nullable"]}}
                for name, spec in result["tables"][table["name"]]["schema"].items()
            ]
    for table in table_summaries:
        counts = Counter(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in tables[table["name"]]
        )
        table["duplicate_rows"] = sum(count - 1 for count in counts.values())
        if table["duplicate_rows"]:
            notes.append(
                f"{table['name']} : {table['duplicate_rows']} ligne(s) répétée(s), conservée(s) en bronze."
            )
    lines = result["path"].read_text().splitlines()
    lines[0] = (
        f"# Carte d’identité{' SQL' if source['format'] == 'sql' else ''} — {source['filename']}"
    )
    lines = [
        f"- Source: {source['filename']}" if line.startswith("- Source: ") else line
        for line in lines
    ]
    summary = {
        "tables": table_summaries,
        "rows": sum(t["rows"] for t in table_summaries),
        "duplicate_rows": sum(t["duplicate_rows"] for t in table_summaries),
        "notes": notes,
    }
    return {
        "tables": tables,
        "summary": summary,
        "report": "\n".join(lines) + "\n",
        "contract": contract,
        "types_catalog": types,
        "table_specs": table_specs,
    }
