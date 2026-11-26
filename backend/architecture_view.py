"""Validate an application's API and assemble the architecture review document."""

import json
import re

from .contracts import Architecture, Requirements


def openapi_document(architecture: Architecture) -> dict:
    paths = {}
    for route, encoded in architecture.api_contract.items():
        method, separator, path = route.partition(" ")
        if not separator or method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ValueError("Use one HTTP method and one path for each API operation")
        if not path.startswith("/") or path.startswith("//") or any(c.isspace() for c in path):
            raise ValueError("Invalid API path")
        operation = json.loads(encoded)
        responses = operation.get("responses") if isinstance(operation, dict) else None
        if not operation or not isinstance(responses, dict) or not responses:
            raise ValueError("An OpenAPI operation needs responses")
        if not any(re.fullmatch(r"2[0-9]{2}", key) for key in responses):
            raise ValueError("Missing success response")
        for code, description in responses.items():
            if code != "default" and not re.fullmatch(r"[1-5][0-9]{2}", code):
                raise ValueError("Invalid response status")
            if not isinstance(description, dict) or not description.get("description"):
                raise ValueError("Missing response description")
        params = operation.get("parameters", [])
        if not isinstance(params, list) or any(not isinstance(p, dict) for p in params):
            raise ValueError("Invalid OpenAPI parameters")
        path_params = {p.get("name") for p in params if p.get("in") == "path" and p.get("required") is True}
        if path_params != set(re.findall(r"\{([^{}]+)\}", path)):
            raise ValueError("Each path parameter must be declared required")
        paths.setdefault(path, {})[method.lower()] = operation
    return {"openapi": "3.1.0", "info": {"title": "Ứng dụng CRUD", "version": "1.0.0"}, "paths": paths}


def validate_architecture(design: Architecture, requirements: Requirements, ref) -> None:
    if design.requirements != ref:
        raise ValueError("Stale requirements reference")
    fr_ids = {item.id for item in requirements.functional}
    if set(design.fr_components) != fr_ids:
        raise ValueError("Every functional requirement needs a component mapping")
    for components in design.fr_components.values():
        if not components or set(components) - design.components.keys():
            raise ValueError("Unknown component in FR mapping")
    descriptions = " ".join(f"{name} {value}" for name, value in design.components.items()).casefold()
    if any(stack not in descriptions for stack in ("fastapi", "react", "sqlite")):
        raise ValueError("The components must implement FastAPI, React, and SQLite")
    openapi_document(design)


def render_architecture(design: Architecture) -> str:
    parts = ["# Thiết kế ứng dụng", "", "## ADR", ""]
    parts.extend(f"- {entry}" for entry in design.adr)
    for title, values in (("Thành phần", design.components), ("Dữ liệu và quan hệ", design.entities)):
        parts.extend(["", f"## {title}", ""])
        parts.extend(f"- **{name}** — {value}" for name, value in values.items())
    parts.extend(["", "## Truy vết FR đến thành phần", "", "```mermaid", "flowchart LR"])
    def label(value):
        return re.sub(r'[^\w .:/-]', ' ', value, flags=re.UNICODE)[:100]
    nodes = {name: f"C{i}" for i, name in enumerate(design.components)}
    for name, node in nodes.items():
        parts.append(f'  {node}["{label(name)}"]')
    for i, (fr, components) in enumerate(design.fr_components.items()):
        parts.append(f'  F{i}["{label(fr)}"]')
        parts.extend(f"  F{i} --> {nodes[name]}" for name in components)
    parts.extend(["```", "", "## OpenAPI", "", "```json",
                  json.dumps(openapi_document(design), ensure_ascii=False, indent=2), "```",
                  "", "## Giao diện", "", design.frontend, "", "## Chiến lược kiểm thử", "",
                  design.test_strategy, ""])
    return "\n".join(parts)
