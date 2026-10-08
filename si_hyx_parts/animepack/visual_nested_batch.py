"""Batch nested scene jobs without mixing title, page or crop identifiers."""
from gemini_api import GeminiError

from .visual_batch import VisualCheckBatcher


def valid(value, schema):
    kind = schema.get("type")
    if kind == "object":
        return (isinstance(value, dict)
                and set(schema.get("required", ())).issubset(value)
                and all(valid(value[key], child) for key, child in
                        schema.get("properties", {}).items() if key in value))
    if kind == "array":
        return (isinstance(value, list)
                and len(value) <= schema.get("maxItems", float("inf"))
                and len(value) >= schema.get("minItems", 0)
                and all(valid(item, schema.get("items", {})) for item in value))
    types = {"integer": lambda v: type(v) is int,
             "number": lambda v: type(v) in (int, float),
             "boolean": lambda v: type(v) is bool,
             "string": lambda v: isinstance(v, str)}
    return types.get(kind, lambda _: True)(value)


class NestedVisualBatcher(VisualCheckBatcher):
    def can_combine(self, first, other):
        return first.schema == other.schema

    def batch_request(self, batch):
        parts = [{"type": "text", "text": (
            "Выполни независимые задания job_id. Все метки page_index, "
            "tile_index, scene_id и ожидаемое произведение действуют только "
            "ВНУТРИ своего задания. Не смешивай изображения, названия и "
            "персонажей разных заданий. Верни jobs: по одному полному ответу "
            "с job_id на каждое задание, даже когда подходящих сцен нет.")}]
        for index, job in enumerate(batch):
            parts.append({"type": "text", "text": f"НАЧАЛО ЗАДАНИЯ job_id={index}"})
            parts.extend(job.parts)
            parts.append({"type": "text", "text": f"КОНЕЦ ЗАДАНИЯ job_id={index}"})
        original = batch[0].schema
        row = dict(original, properties={**original["properties"],
                                         "job_id": {"type": "integer"}},
                   required=[*original["required"], "job_id"])
        schema = {"type": "object", "properties": {
            "jobs": {"type": "array", "items": row,
                     "minItems": len(batch), "maxItems": len(batch)}},
            "required": ["jobs"]}
        return parts, schema

    def batch_verdicts(self, response, batch):
        rows = response.get("jobs") if isinstance(response, dict) else None
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise GeminiError("Gemini вернула неполную группу заданий по сценам")
        found = {}
        for row in rows:
            ident = row.get("job_id") if isinstance(row, dict) else None
            if (type(ident) is not int or not 0 <= ident < len(batch)
                    or ident in found or not valid(row, batch[ident].schema)):
                raise GeminiError("Gemini вернула неверный идентификатор или ответ сцены")
            found[ident] = {k: v for k, v in row.items() if k != "job_id"}
        return found
