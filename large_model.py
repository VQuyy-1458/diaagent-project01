"""Shared schema for the Kaggle Diabetes Prediction Dataset."""
import math

FIELDS = ("gender", "age", "hypertension", "heart_disease", "smoking_history", "bmi",
          "HbA1c_level", "blood_glucose_level")
CATEGORIES = {"gender": ("Female", "Male"), "smoking_history":
              ("never", "No Info", "current", "former", "ever", "not current")}
RANGES = {"age": (.08, 80), "hypertension": (0, 1), "heart_disease": (0, 1),
          "bmi": (10, 96), "HbA1c_level": (3.5, 9), "blood_glucose_level": (80, 300)}
LABS = FIELDS[-2:]


def clean(profile):
    values = {}
    for field in FIELDS:
        raw = profile.get(field)
        if field in LABS and raw in (None, ""):
            continue
        if raw in (None, ""):
            raise ValueError(f"Cần bổ sung {field}.")
        if field in CATEGORIES:
            if raw not in CATEGORIES[field]:
                raise ValueError(f"Giá trị không hợp lệ cho {field}.")
            values[field] = raw
        else:
            value = float(str(raw).replace(",", "."))
            low, high = RANGES[field]
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{field} phải nằm trong khoảng {low}–{high}.")
            if field in ("hypertension", "heart_disease") and value not in (0, 1):
                raise ValueError(f"{field} chỉ nhận 0 hoặc 1.")
            values[field] = value
    return values


def encode(values, fields):
    vector = []
    for field in fields:
        if field in CATEGORIES:
            vector.extend(int(values[field] == option) for option in CATEGORIES[field])
        else:
            vector.append(float(values[field]))
    return vector
