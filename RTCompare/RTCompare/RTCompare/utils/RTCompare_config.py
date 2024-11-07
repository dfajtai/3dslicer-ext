from dataclasses import dataclass
import typing


@dataclass
class RTCompareMeasurement:
    patient_id: int
    patient_name: str
    patient_sex: str
    patient_age: str
    study_desc: str
    study_date: str
    import_timestamp:str
    series_description: str
    modality:str
    series_uid: str
    files:list[str]
    