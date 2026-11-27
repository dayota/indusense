# Roadmap MLOps : Préparation d'un Dataset Tabulaire

Ce document présente les étapes essentielles pour transformer des données brutes en un dataset propre et prêt pour l'entraînement d'un modèle d'apprentissage automatique (Machine Learning). Il est destiné à vous accompagner dans la compréhension du pipeline de préparation des données.

## Architecture du Pipeline Tabulaire

```mermaid
flowchart TD
    subgraph SOURCES["📂 Sources Tabulaires"]
        S1[CSV / Parquet\nEx: Ventes, Clients]
        S2[Base SQL\nEx: Transactions]
    end

    subgraph INGESTION["🟫 Ingestion & Découverte"]
        I1[Validation Schéma]
        I2[Profil Volumétrique]
        I3[Vérification Clés]

        LIB_I[> pandas, pandera,\ngreat_expectations]
    end

    subgraph EDA["🔍 Analyse Exploratoire"]
        E1[Distributions Univariées]
        E2[Corrélations Bivariées]
        E3[Saisonnalité & Tendances temporelles]

        LIB_E[> matplotlib, seaborn,\nstatsmodels]
    end

    subgraph CLEANING["🧹 Nettoyage"]
        C1[Déduplication]
        C2[Normalisation Formats]
        C3[Encodage Catégorique basique]

        LIB_C[> pandas, pyjanitor]
    end

    subgraph OUTLIERS["🚨 Traitement des Outliers"]
        O1[Limites Physiques / Métier]
        O2[Z-Score / IQR]
        O3[Isolation Forest / LOF]

        LIB_O[> scipy.stats, scikit-learn]
    end

    subgraph IMPUTATION["💉 Imputation des Manquants"]
        M1[Stratégie par colonne\nMean, Median, Mode]
        M2[Imputation Multivariée\nKNN, IterativeImputer]
        M3[Interpolation Temporelle]

        LIB_M[> scikit-learn, numpy]
    end

    subgraph FEATURES["🥈 Feature Engineering"]
        F1[Création Variables\nDates, Ratios, Bins]
        F2[Variables Temporelles\nLags, Rolling Windows]
        F3[Features Synthétiques\nDeep Feature Synthesis]

        LIB_F[> scikit-learn, featuretools,\ntsfresh]
    end

    subgraph VALIDATION["🥇 Validation Gold"]
        V1[Équilibre des Classes]
        V2[Contrôle Fuite de Données\nData Leakage]
        V3[Split Train / Val / Test]

        LIB_V[> scikit-learn, numpy]
    end

    S1 & S2 --> I1
    I1 --> I2 --> I3
    I3 -.-> LIB_I

    I3 --> E1 --> E2 --> E3
    E3 -.-> LIB_E

    E3 --> C1 --> C2 --> C3
    C3 -.-> LIB_C

    C3 --> O1 --> O2 --> O3
    O3 -.-> LIB_O

    O3 --> M1 --> M2 --> M3
    M3 -.-> LIB_M

    M3 --> F1 --> F2 --> F3
    F3 -.-> LIB_F

    F3 --> V1 --> V2 --> V3
    V3 -.-> LIB_V
```

## Étapes Détaillées et Librairies Python

### 1. Ingestion et Découverte
La première étape valide la structure et la volumétrie des données brutes. On s'assure que les types de colonnes (entiers, chaînes, dates) correspondent aux attentes et que les clés primaires sont uniques.
**Librairies :**
- `pandas` pour la lecture (`read_csv`, `read_parquet`, `read_sql`).
- `pandera` ou `great_expectations` pour la validation stricte de schémas (types, valeurs nulles tolérées).

### 2. Analyse Exploratoire (EDA)
L'EDA permet de comprendre la distribution des données et d'identifier les valeurs atypiques avant tout traitement. Même sur des données tabulaires, si une colonne date existe, l'analyse des tendances temporelles reste cruciale.
**Librairies :**
- `matplotlib` et `seaborn` pour les visualisations (histogrammes, boxplots, heatmaps de corrélation).
- `statsmodels` pour la décomposition des séries temporelles (saisonnalité, tendance).

### 3. Nettoyage
On harmonise les données en supprimant les doublons, en uniformisant les textes (majuscules/minuscules) et en corrigeant les types de données.
**Librairies :**
- `pandas` pour les manipulations de base (`drop_duplicates`, `.str.lower()`).
- `pyjanitor` pour enchaîner des opérations de nettoyage de manière élégante et lisible.

### 4. Traitement des Outliers
Il faut distinguer les erreurs de saisie des valeurs extrêmes légitimes. Les approches combinent des règles métier et des méthodes statistiques.
**Librairies :**
- `scipy.stats` pour les calculs de Z-score et les limites IQR.
- `scikit-learn` pour des algorithmes de détection multidimensionnelle comme `IsolationForest` ou `LocalOutlierFactor`.

### 5. Imputation des Manquants
L'absence de données est compensée par différentes stratégies selon la colonne. Les données temporelles bénéficient de méthodes spécifiques comme l'interpolation.
**Librairies :**
- `numpy` pour la gestion des `np.nan`.
- `scikit-learn.impute` pour `SimpleImputer` (moyenne, médiane) et `IterativeImputer` (modélisation des manquants via les autres colonnes).
- `pandas` pour l'interpolation temporelle (`.interpolate(method='time')`).

### 6. Feature Engineering
L'objectif est de créer de nouvelles variables pour aider le modèle. Cela inclut l'extraction d'informations des dates (jour de la semaine, mois) et la création de variables retardées (lags) si la dimension temporelle est pertinente.
**Librairies :**
- `scikit-learn.preprocessing` pour l'encodage (`OneHotEncoder`, `OrdinalEncoder`) et la mise à l'échelle (`StandardScaler`, `MinMaxScaler`).
- `featuretools` pour la génération automatique de features (Deep Feature Synthesis) croisant plusieurs tables.
- `tsfresh` pour extraire massivement des caractéristiques statistiques sur les composantes temporelles du tableau.

### 7. Validation Gold
La dernière étape prépare le split pour le Machine Learning, en s'assurant qu'aucune fuite d'information ne s'est produite depuis le futur vers le passé, et que les classes cibles sont suffisamment équilibrées.
**Librairies :**
- `scikit-learn.model_selection` pour `train_test_split` (avec l'argument `shuffle=False` si la chronologie doit être respectée).
- `imblearn` (imbalanced-learn) pour des techniques comme SMOTE si les données sont déséquilibrées.