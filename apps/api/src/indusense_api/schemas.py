from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator



class ModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class VersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_version_id: UUID | None = None
    preparation: bool = False


class StageValidationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: Literal["bronze", "silver"]


class UploadEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    dataset_name: str = Field(min_length=1, max_length=120)
    contract: str | None = Field(default=None, max_length=120)
    contract_mode: Literal["existing", "generate"] = "existing"
    contract_yaml: str | None = Field(default=None, min_length=1, max_length=200000)
    sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    mode: Literal["snapshot"] = "snapshot"

    @field_validator("dataset_name")
    @classmethod
    def no_controls(cls, value):
        if any(ord(char) < 32 for char in value):
            raise ValueError(
                "Le nom du dataset ne doit pas contenir de caractères de contrôle"
            )
        return value


class SilverContractInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    yaml: str = Field(min_length=1, max_length=200000)
    base_revision: int = Field(default=0, ge=0)


class SilverPrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_id: UUID


class SilverResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["discard", "reintegrate"]
    values: dict[str, str | int | float | bool | None] | None = None
    reason: str = Field(min_length=1, max_length=2000)


class SqlTableContractChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str = Field(min_length=1, max_length=255)
    mode: Literal["existing", "generate"] = "generate"
    contract: str | None = Field(default=None, max_length=120)


class SqlInspectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encoding: str = Field(default="utf-8", min_length=1, max_length=64)


class PreparationContractChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    mode: Literal["existing", "generate"] = "generate"
    contract: str | None = Field(default=None, max_length=120)
    encoding: str = Field(default="utf-8", min_length=1, max_length=64)
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    row_delimiter: Literal["\n", "\r\n"] = "\n"
    tables: list[SqlTableContractChoice] | None = Field(default=None, min_length=1)


class MigrationApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hash: str = Field(pattern="^[a-f0-9]{64}$")


class PreparationContractLoad(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[PreparationContractChoice] = Field(min_length=1, max_length=10)


class SqlTableContractSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str = Field(min_length=1, max_length=255)
    yaml: str | None = Field(default=None, min_length=1, max_length=200000)
    config: dict | None = None


class PreparationContractSaveFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    yaml: str | None = Field(default=None, max_length=200000)
    revision: int = Field(ge=0)
    tables: list[SqlTableContractSave] | None = Field(default=None, min_length=1)
    config: dict | None = None


class PreparationContractSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[PreparationContractSaveFile] = Field(min_length=1, max_length=10)


class TechnicalColumnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str = Field(default="data", min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=63)
    source: str = Field(min_length=1, max_length=255)
    converter: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=64)
    format: str | None = Field(default=None, min_length=1, max_length=120)
    pattern: str | None = Field(default=None, max_length=500)
    nullable: bool = True


class PreparationCreateFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    revision: int = Field(ge=1)
    technical_columns: list[TechnicalColumnInput] = Field(default_factory=list, max_length=100)


class PreparationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[PreparationCreateFile] = Field(min_length=1, max_length=10)
