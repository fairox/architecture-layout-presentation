"""In-memory stand-in for Archicad + Tapir, used as a TapirClient transport."""

from __future__ import annotations

import itertools
from typing import Any


class FakeArchicad:
    def __init__(
        self,
        elements: list[str] | None = None,
        selected: list[str] | None = None,
        properties: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self.elements: list[str] = list(elements or [])
        self.selected: list[str] = list(selected or [])
        self.properties = dict(properties or {})  # (group, name) -> property guid
        self.values: dict[tuple[str, str], Any] = {}  # (element, property) -> value
        self.positions: dict[str, tuple[float, float, float]] = {}
        self.requests: list[dict[str, Any]] = []
        self._ids = (f"copy-{n}" for n in itertools.count(1))

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        command = request["command"]
        params = request.get("parameters", {})
        if command == "API.ExecuteAddOnCommand":
            name = params["addOnCommandId"]["commandName"]
            handler = getattr(self, f"_tapir_{name}", None)
            if handler is None:
                return {"succeeded": False, "error": {"message": f"unknown Tapir {name}"}}
            output = handler(params.get("addOnCommandParameters", {}))
            return {"succeeded": True, "result": {"addOnCommandResponse": output}}
        handler = getattr(self, "_" + command.replace(".", "_"), None)
        if handler is None:
            return {"succeeded": False, "error": {"message": f"unknown {command}"}}
        return {"succeeded": True, "result": handler(params)}

    def commands(self) -> list[str]:
        """Command names received, Tapir ones as ``Tapir.<name>``."""
        names = []
        for r in self.requests:
            if r["command"] == "API.ExecuteAddOnCommand":
                names.append("Tapir." + r["parameters"]["addOnCommandId"]["commandName"])
            else:
                names.append(r["command"])
        return names

    # -- Tapir ---------------------------------------------------------------

    def _tapir_GetSelectedElements(self, _: dict) -> dict:
        return {"elements": [{"elementId": {"guid": g}} for g in self.selected]}

    def _tapir_MoveElements(self, params: dict) -> dict:
        for item in params["elementsWithMoveVectors"]:
            v = item["moveVector"]
            vector = (v["x"], v["y"], v["z"])
            if item.get("copy"):
                new = next(self._ids)
                self.elements.append(new)
                self.positions[new] = vector
            else:
                self.positions[item["elementId"]["guid"]] = vector
        return {}

    # -- built-in API --------------------------------------------------------

    def _API_GetAllElements(self, _: dict) -> dict:
        return {"elements": [{"elementId": {"guid": g}} for g in self.elements]}

    def _API_GetPropertyIds(self, params: dict) -> dict:
        out = []
        for p in params["properties"]:
            guid = self.properties.get(tuple(p["localizedName"]))
            out.append({"propertyId": {"guid": guid}} if guid else {"error": {"code": 1}})
        return {"properties": out}

    def _API_SetPropertyValuesOfElements(self, params: dict) -> dict:
        for v in params["elementPropertyValues"]:
            key = (v["elementId"]["guid"], v["propertyId"]["guid"])
            self.values[key] = v["propertyValue"]["value"]
        return {"executionResults": [{"success": True}] * len(params["elementPropertyValues"])}
