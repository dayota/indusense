"""Cartes d’identité CSV pilotées par des contrats YAML."""

import csv
import io
import re
from decimal import Decimal, localcontext
from statistics import median
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import CONVERTERS, load_configuration

ROOT = Path(__file__).resolve().parents[1]
PARIS = ZoneInfo("Europe/Paris")
DEFAULT_TYPES = ROOT / "config" / "types.yaml"


def infer_columns(frame, contract, types):
    columns, issues = {}, []
    expected = contract["columns"]
    missing = [name for name, spec in expected.items() if spec.get("required", True) and name not in frame.columns]
    if missing:
        raise ValueError(f"Colonnes obligatoires absentes : {missing}")
    for name in frame.columns:
        series = frame[name]
        spec = expected.get(name)
        if spec is None:
            for rule in contract.get("column_rules", []):
                if re.search(rule["pattern"], name):
                    spec = {key: value for key, value in rule.items() if key != "pattern"}
                    break
        if spec is None:
            if contract.get("extra_columns", "infer") == "error":
                raise ValueError(f"Colonne supplémentaire : {name}")
            kind = infer_type(series, types, name)
            spec = {"type": kind}
        kind = spec["type"]
        options = {**types[kind], **spec}
        # Un nouveau format de colonne ne doit pas conserver la regex de l’ancien.
        if "format" in spec and "pattern" not in spec:
            options.pop("pattern", None)
        converted = CONVERTERS[options["converter"]](series, options)
        if "allowed" in spec:
            converted = converted.where(converted.isin(spec["allowed"]))
        if "min" in spec:
            converted = converted.where(converted.ge(spec["min"]))
        if "max" in spec:
            converted = converted.where(converted.le(spec["max"]))
        invalid = series.notna() & converted.isna()
        if invalid.any():
            examples = ", ".join(repr(value) for value in series[invalid].head(3))
            issues.append(
                f"{name} : {int(invalid.sum())} valeur(s) incompatible(s) avec {kind} "
                f"exclue(s) des statistiques. Exemples : {examples}"
            )
        if not spec.get("nullable", True) and series.isna().any():
            issues.append(f"{name} : {int(series.isna().sum())} valeur(s) manquante(s) interdite(s).")
        columns[name] = {"type": kind, "values": converted, "options": options}
    return columns, issues


def infer_type(series, types, name):
    if name.lower().endswith(("_id", "_badge")):
        return "IDENTITY"
    present = series.dropna()
    if not present.empty:
        for kind in ("DATE", "TIME", "DATETIME", "INTEGER", "FLOAT"):
            options = types[kind]
            if CONVERTERS[options["converter"]](present, options).notna().all():
                return kind
    return "TEXT"


def compute_statistics(columns):
    statistics = []
    for name, info in columns.items():
        selected = info["options"].get("statistics", [])
        if not selected:
            continue
        values = info["values"].dropna()
        row = dict.fromkeys(("min", "max", "mean", "median"))
        row.update(name=name, type=info["type"])
        if not values.empty:
            if info["options"]["converter"] == "decimal":
                # Aucun passage par float/numpy pour les montants exacts.
                numbers = list(values)
                with localcontext() as context:
                    span = max(v.adjusted() for v in numbers) - min(v.as_tuple().exponent for v in numbers) + 1
                    context.prec = max(28, span + len(str(len(numbers))) + 8)
                    operations = {"min": min, "max": max, "median": median,
                                  "mean": lambda seq: sum(seq, Decimal(0)) / len(seq)}
                    for operation in selected:
                        row[operation] = operations[operation](numbers)
            else:
                for operation in selected:
                    row[operation] = getattr(values, operation)()
        statistics.append(row)
    return statistics


def read_text_source(source):
    source = Path(source).resolve(strict=True)
    raw = source.read_bytes()
    notes = []
    for charset in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(charset, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    if charset != "utf-8-sig":
        notes.append(
            f"UTF-8 invalide : lecture en {charset}, encodage de repli "
            "non déterminable avec certitude à partir des seuls octets."
        )
    charset_label = (
        "UTF-8 avec BOM" if raw.startswith(b"\xef\xbb\xbf") else "UTF-8"
    ) if charset == "utf-8-sig" else charset
    if not text.strip():
        raise ValueError(f"Fichier vide : {source}")
    return text, {"source": source, "size": len(raw), "charset": charset_label, "notes": notes}


def read_csv_source(source):
    text, metadata = read_text_source(source)
    try:
        separator = csv.Sniffer().sniff(text[:65536], delimiters=",;\t").delimiter
    except csv.Error as exc:
        raise ValueError(f"Séparateur indéterminé pour {metadata['source']}") from exc
    frame = pd.read_csv(
        io.StringIO(text), sep=separator, dtype="string", keep_default_na=False,
        skip_blank_lines=False, on_bad_lines="error",
    )
    frame = frame.replace(r"^\s*$", pd.NA, regex=True)
    return frame, {**metadata, "separator": separator}


def render_markdown(metadata, frame, columns, statistics, begin, end):
    def escape(value):
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    def format_value(value, name, aggregate=False):
        if value is None or pd.isna(value):
            return "N/A"
        options = columns[name]["options"]
        if options["converter"] in ("datetime", "datetime_utc"):
            return value.strftime(options["format"])
        if options["converter"] == "integer" and not aggregate:
            return str(int(value))
        if isinstance(value, Decimal):
            return str(value)
        return format(float(value), ".12g")

    size = float(metadata["size"])
    unit = "o"
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if size < 1024 or unit == "To":
            break
        size /= 1024
    separator_label = "tabulation" if metadata["separator"] == "\t" else metadata["separator"]
    lines = [
        f"# Carte d’identité — {metadata['source'].name}", "",
        f"- Source: {metadata['source']}",
        f"- Filsize: {size:.2f} {unit}",
        f"- ProcessBeginAt: {begin:%H:%M:%S}",
        f"- ProcessEndAt: {end:%H:%M:%S}",
        f"- Charset: {metadata['charset']}",
        f"- Rows Number: {len(frame)}",
        f"- Cols Number: {len(frame.columns)}",
        f"- Date: {begin:%Y-%m-%d} (Europe/Paris)",
        f"- Séparateur: {separator_label}", "",
        "## Column list", "", "| Colname | Infered Type |", "| --- | --- |",
    ]
    lines.extend(f"| {escape(name)} | {info['type']} |" for name, info in columns.items())
    lines.extend([
        "", "## Statistiques", "",
        "| Col name | Min value | Max value | Mean value | Median value |",
        "| --- | --- | --- | --- | --- |",
    ])
    for row in statistics:
        values = [escape(row["name"])] + [
            escape(format_value(row[key], row["name"], key in ("mean", "median")))
            for key in ("min", "max", "mean", "median")
        ]
        lines.append("| " + " | ".join(values) + " |")
    lines.extend([
        "", "Les valeurs manquantes et les valeurs invalides signalées ci-dessous sont exclues "
        "des calculs. N/A indique une statistique non applicable ou sans valeur exploitable.",
        "Les identifiants sont conservés comme chaînes et exclus des statistiques numériques.",
        "", "## Observations", "",
    ])
    notes = metadata["notes"] or ["Aucune anomalie de conversion détectée."]
    lines.extend(f"- {escape(note)}" for note in notes)
    return "\n".join(lines) + "\n"


def generate_identity(source, output_stem, *, contract_path, types_path=DEFAULT_TYPES, root=ROOT):
    contract, types = load_configuration(contract_path, types_path)
    root = Path(root)
    begin = datetime.now(PARIS)
    frame, metadata = read_csv_source(source)
    columns, issues = infer_columns(frame, contract, types)
    metadata["notes"].extend(issues)
    statistics = compute_statistics(columns)
    output_dir = root / "artifacts" / "ingestion" / "identities" / begin.strftime("%Y%m%d")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{output_stem}_{begin:%H%M%S}.md"
    end = datetime.now(PARIS)
    report = render_markdown(metadata, frame, columns, statistics, begin, end)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(report)
    return {
        "path": output, "rows": len(frame), "cols": len(frame.columns),
        "columns": columns, "statistics": statistics, "notes": metadata["notes"],
        "begin": begin, "end": end,
    }
