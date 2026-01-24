# CDSLtoEventLog
**Article Title:** *Improving Hospital Process Management through Process Mining: A Case Study on COVID-19 Clinical Pathways* \
**Authors**: Ardimento Pasquale, Bernardi Mario Luca, Cimitile Marta, La Torre Samuele \
**Article DOI**: TBD

### Abstract
This study analyzes COVID-19 care pathways using the COVID Data for Shared Learning dataset. We build a transparent, reproducible pipeline that transforms heterogeneous clinical tables into a process mining-ready event log and applies discovery, declarative conformance checking, and outcome analysis. The reconstructed pathways highlight the monitoring backbone of inpatient care, variability at the Emergency department-admission interface, and outcome differences driven by age and exposure to intensive care units. These insights support triage standardization, capacity planning, and step-down coordination from intensive care units to lower-acuity wards, showing how process mining can inform evidence-based hospital governance.

### Repository Contents
This repository implements the event log extraction pipeline for the **Covid Data for Shared Learning (CDSL)** dataset.

- **`CDSL_Log_Extractor.ipynb`**: The primary interactive notebook. It documents the full pipeline, from data preparation and cleaning to the final XES export.
- **`CDSL_Log_Extractor.py`**: A Python script version of the extraction logic, intended for headless or automated execution.
- **`Mapping_Tables.pdf`**: Schema reference defining the mapping between the original dataset columns and the event log's activities attributes.

### Data access
his research utilizes the **Covid Data for Shared Learning (CDSL)** dataset, pubblicly available at: [PhysioNet: Covid Data for Shared Learning v1.0.0](https://physionet.org/content/covid-data-shared-learning/1.0.0/).
> **Note:** While this dataset is hosted on a public repository, access is restricted. Users must be **credentialed PhysioNet users** and must request the data owner for access.
