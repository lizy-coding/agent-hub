"""The current, Git-owned declaration. No discovery or executable templates."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "forge.workflow.v1"
DEFAULT_CATALOG = Path(__file__).with_name("catalog.json")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
        raise ValueError("Invalid identifier")
    return value


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def validate_inputs(schema, value):
    if not isinstance(value, dict) or set(value) - set(schema["properties"]):
        raise ValueError("Unknown workflow input")
    result = {}
    for name, rule in schema["properties"].items():
        if name not in value and "default" not in rule:
            raise ValueError(f"Missing input: {name}")
        item = value[name] if name in value else deepcopy(rule["default"])
        kind = rule["type"]
        if kind == "integer":
            valid = type(item) is int and rule["minimum"] <= item <= rule["maximum"]
        elif kind == "boolean":
            valid = type(item) is bool
        elif kind == "string":
            valid = isinstance(item, str) and len(item) <= rule["maxLength"]
        else:
            raise ValueError("Unsupported input type")
        if not valid:
            raise ValueError(f"Invalid input: {name}")
        result[name] = item
    return result


class Catalog:
    def __init__(self, document):
        document = deepcopy(document)
        try:
            if set(document) != {"schema", "capabilities", "workflows"} or document["schema"] != SCHEMA:
                raise ValueError("Unsupported catalog schema")
            capabilities = document["capabilities"]
            if not isinstance(capabilities, list) or not 1 <= len(capabilities) <= 64:
                raise ValueError("Invalid capability list")
            known = set()
            for item in capabilities:
                if set(item) != {"id", "version", "title", "effect"}:
                    raise ValueError("Invalid capability")
                key = (identifier(item["id"]), item["version"])
                if type(item["version"]) is not int or item["version"] < 1 or key in known:
                    raise ValueError("Invalid capability version")
                if not all(isinstance(item[k], str) and 0 < len(item[k]) <= 200 for k in ("title", "effect")):
                    raise ValueError("Invalid capability metadata")
                known.add(key)
            flows = document["workflows"]
            if not isinstance(flows, list) or not 1 <= len(flows) <= 32:
                raise ValueError("Invalid workflow list")
            ids = set()
            for flow in flows:
                if set(flow) != {"schema", "id", "version", "title", "source", "steps", "output", "inputSchema"}:
                    raise ValueError("Invalid workflow declaration")
                identifier(flow["id"])
                if flow["id"] in ids or flow["schema"] != SCHEMA or type(flow["version"]) is not int or flow["version"] < 1:
                    raise ValueError("Only one current version per workflow is allowed")
                ids.add(flow["id"])
                if not all(isinstance(flow[k], str) and 0 < len(flow[k]) <= 200 for k in ("title", "source")):
                    raise ValueError("Invalid workflow metadata")
                steps = flow["steps"]
                if not isinstance(steps, list) or not 1 <= len(steps) <= 16:
                    raise ValueError("Invalid steps")
                step_ids = set()
                for step in steps:
                    if set(step) != {"id", "capability", "version"}:
                        raise ValueError("Invalid step")
                    identifier(step["id"])
                    if step["id"] in step_ids or type(step["version"]) is not int or (step["capability"], step["version"]) not in known:
                        raise ValueError("Unknown capability or duplicate step")
                    step_ids.add(step["id"])
                output = flow["output"]
                if set(output) != {"kind", "columns"} or output["kind"] != "table":
                    raise ValueError("Only bounded table output is supported")
                columns = output["columns"]
                if not isinstance(columns, list) or not 1 <= len(columns) <= 20 or any(not isinstance(c, str) or not 0 < len(c) <= 100 for c in columns) or len(set(columns)) != len(columns):
                    raise ValueError("Invalid output columns")
                schema = flow["inputSchema"]
                if set(schema) != {"type", "additionalProperties", "properties"} or schema["type"] != "object" or schema["additionalProperties"] is not False:
                    raise ValueError("Inputs must be a closed object")
                if not isinstance(schema["properties"], dict) or not 1 <= len(schema["properties"]) <= 32:
                    raise ValueError("Invalid input properties")
                for name, rule in schema["properties"].items():
                    identifier(name)
                    kind = rule["type"]
                    bounds = {"integer": {"minimum", "maximum"}, "string": {"maxLength"}, "boolean": set()}
                    if kind not in bounds or set(rule) != {"type", "title", "default"} | bounds[kind]:
                        raise ValueError("Unsupported input rule")
                    if not isinstance(rule["title"], str) or not 0 < len(rule["title"]) <= 100:
                        raise ValueError("Invalid input title")
                    if kind == "integer" and (type(rule["minimum"]) is not int or type(rule["maximum"]) is not int or rule["minimum"] > rule["maximum"]):
                        raise ValueError("Invalid integer bounds")
                    if kind == "string" and (type(rule["maxLength"]) is not int or not 0 <= rule["maxLength"] <= 4096):
                        raise ValueError("Invalid string bound")
                validate_inputs(schema, {})
            encoded = encode(document)
            if len(encoded.encode()) > 100_000:
                raise ValueError("Catalog too large")
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError("Malformed catalog") from error
        self.document = document
        self.digest = hashlib.sha256(encoded.encode()).hexdigest()

    @classmethod
    def load(cls, path=DEFAULT_CATALOG):
        raw = Path(path).read_bytes()
        if len(raw) > 100_000:
            raise ValueError("Catalog too large")
        return cls(json.loads(raw))
