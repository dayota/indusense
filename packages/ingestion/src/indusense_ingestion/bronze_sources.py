"""Adaptateurs de lecture explicite : CSV en flux, dump SQL analysé sans exécution."""
import csv
from pathlib import Path
from sqlglot.errors import SqlglotError

from .bronze_domain import SourceColumn, SourceInspectionError, SourceSchema, SourceSpec


def source_spec(config):
    source = config["source"]
    return SourceSpec(source["path"], source["format"], source["encoding"], source.get("table"),
                      source.get("field_delimiter", ","), source.get("row_delimiter", "\n").replace("\\r", "\r").replace("\\n", "\n"))


class FilesystemSourceInspector:
    def __init__(self, root, overrides=None):
        self.root = Path(root).resolve()
        self.overrides = overrides or {}

    def path(self, source):
        if source.path in self.overrides:
            return Path(self.overrides[source.path])
        declared = Path(source.path)
        relative = None
        if declared.is_absolute():
            # /datas est un chemin logique portable, relatif à la racine fournie au moteur.
            try:
                relative = declared.relative_to('/datas/ingestion')
            except ValueError:
                raise SourceInspectionError('Seuls les chemins absolus /datas/ingestion/ sont autorisés') from None
        elif declared.parts[:2] == ('datas', 'ingestion'):
            relative = declared.relative_to('datas/ingestion')
        if relative is not None:
            if len(relative.parts) != 4 or relative.parts[2] != 'inputs' or not relative.parts[1].isdigit():
                raise SourceInspectionError('Une source ingérée doit être dans <modèle>/<version>/inputs/<fichier>')
            path = (self.root / 'datas/ingestion' / relative).resolve()
            if '..' in relative.parts or not path.is_relative_to(self.root / 'datas/ingestion'):
                raise SourceInspectionError('Le chemin source doit rester dans datas/ingestion')
            return path
        path = (self.root / source.path).resolve()
        if not path.is_relative_to(self.root) or Path(source.path).is_absolute():
            raise SourceInspectionError("Le chemin source doit être relatif à la racine du projet")
        return path

    def inspect(self, source):
        try:
            if source.format == "CSV":
                with self.path(source).open(encoding=source.encoding, newline="") as stream:
                    lines = CsvLines(stream, source.row_delimiter)
                    headers = next(csv.reader(lines, delimiter=source.field_delimiter, strict=True), [])
                    lines.check_record_end()
                if headers:
                    headers[0] = headers[0].removeprefix("\ufeff")
                if not headers or any(not name for name in headers) or len(set(headers)) != len(headers):
                    raise SourceInspectionError("En-têtes CSV vides ou dupliqués")
                return SourceSchema(tuple(SourceColumn(name, True) for name in headers), None)
            table = self.sql_tables(source).get(source.table)
            if table is None:
                raise SourceInspectionError(f"{source.path}:{source.table} : table absente")
            supplied = {name for names in table["insert_columns"] for name in names}
            return SourceSchema(tuple(SourceColumn(name, name in supplied) for name in table["schema"]), len(table["rows"]))
        except (OSError, UnicodeError, LookupError, ValueError, csv.Error, SqlglotError) as error:
            raise SourceInspectionError(f"{source.path}: {error}") from None

    def sql_tables(self, source):
        from .sql_ingestion import parse_sql_source
        return parse_sql_source(self.path(source).read_text(encoding=source.encoding))[0]

    def rows(self, source):
        if source.format == "SQL":
            from .sql_ingestion import Unevaluated
            for row in self.sql_tables(source)[source.table]["rows"]:
                if any(isinstance(value, Unevaluated) for value in row.values()):
                    raise SourceInspectionError("Expression SQL non littérale : aucune expression ne sera exécutée")
                yield row
            return
        try:
            with self.path(source).open(encoding=source.encoding, newline="") as stream:
                lines = CsvLines(stream, source.row_delimiter)
                reader = csv.reader(lines, delimiter=source.field_delimiter, strict=True)
                headers = next(reader)
                lines.check_record_end()
                headers[0] = headers[0].removeprefix("\ufeff")
                for number, values in enumerate(reader, 1):
                    lines.check_record_end()
                    if len(values) != len(headers):
                        raise SourceInspectionError(f"{source.path}: ligne {number}: {len(values)} champs au lieu de {len(headers)}")
                    yield dict(zip(headers, values))
        except (OSError, UnicodeError, LookupError, ValueError, csv.Error) as error:
            raise SourceInspectionError(f"{source.path}: {error}") from None


class CsvLines:
    """Vérifier le séparateur d'enregistrement sans toucher aux sauts de ligne dans les cellules."""
    def __init__(self, stream, delimiter):
        self.stream, self.delimiter, self.last = stream, delimiter, ""

    def __iter__(self): return self

    def __next__(self):
        self.last = next(self.stream)
        return self.last

    def check_record_end(self):
        ending = "\r\n" if self.last.endswith("\r\n") else "\n" if self.last.endswith("\n") else "\r" if self.last.endswith("\r") else ""
        if ending and ending != self.delimiter:
            raise SourceInspectionError("Fin de ligne différente du source.row_delimiter déclaré")
