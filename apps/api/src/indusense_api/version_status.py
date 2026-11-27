from enum import StrEnum


class ModelVersionStatus(StrEnum):
    INGESTION_BRONZE = "ingestion-bronze"
    INGESTION_SILVER = "ingestion-silver"
    INGESTION_GOLD = "ingestion-gold"
    TRAINING = "training"
    CHALLENGER = "challenger"
    CHAMPION = "champion"
