"""Contrat du domaine d'inspection ; aucun pilote, parseur ou accès disque."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SourceSpec:
    path: str
    format: str
    encoding: str
    table: str | None = None
    field_delimiter: str = ","
    row_delimiter: str = "\n"


@dataclass(frozen=True)
class SourceColumn:
    name: str
    provided: bool


@dataclass(frozen=True)
class SourceSchema:
    columns: tuple[SourceColumn, ...]
    rows: int | None


@dataclass(frozen=True)
class ValidationIssue:
    location: str
    message: str


class SourceInspectionError(ValueError):
    pass


class SourceInspectorPort(Protocol):
    def inspect(self, source: SourceSpec) -> SourceSchema: ...
