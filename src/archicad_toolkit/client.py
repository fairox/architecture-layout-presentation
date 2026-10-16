"""Thin client for the Archicad JSON API and Tapir add-on commands.

Archicad listens on http://127.0.0.1:19723 (the first port it can bind in the
19723-19744 range). Built-in commands are posted as ``{"command": "API.X"}``.
Tapir commands go through ``API.ExecuteAddOnCommand`` with the
``TapirCommand`` namespace.

All network I/O happens in a *transport*: a callable that takes a request dict
and returns the decoded response dict. Tests pass a fake transport, so nothing
here needs Archicad running.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Iterable

Transport = Callable[[dict[str, Any]], dict[str, Any]]

DEFAULT_URL = "http://127.0.0.1:19723"
TAPIR_NAMESPACE = "TapirCommand"


class ArchicadError(RuntimeError):
    """Raised when Archicad or Tapir reports a failed command."""


def http_transport(url: str = DEFAULT_URL, timeout: float = 30.0) -> Transport:
    """Return a transport that POSTs JSON to a running Archicad instance."""

    def send(request: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(request).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return send


def element_ids(guids: Iterable[str]) -> list[dict[str, Any]]:
    """Wrap GUID strings in the ``{"elementId": {"guid": ...}}`` shape."""
    return [{"elementId": {"guid": g}} for g in guids]


class TapirClient:
    """Small wrapper around the commands this toolkit needs."""

    def __init__(self, transport: Transport | None = None) -> None:
        self._send = transport or http_transport()

    # -- low level -----------------------------------------------------------

    def api(self, command: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a built-in JSON API command such as ``API.GetAllElements``."""
        request: dict[str, Any] = {"command": command}
        if parameters is not None:
            request["parameters"] = parameters
        response = self._send(request)
        if not response.get("succeeded", False):
            raise ArchicadError(f"{command} failed: {response.get('error')}")
        return response.get("result", {})

    def tapir(self, name: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a Tapir add-on command such as ``GetSelectedElements``."""
        result = self.api(
            "API.ExecuteAddOnCommand",
            {
                "addOnCommandId": {"commandNamespace": TAPIR_NAMESPACE, "commandName": name},
                "addOnCommandParameters": parameters or {},
            },
        )
        output = result.get("addOnCommandResponse", {})
        if isinstance(output, dict) and output.get("succeeded") is False:
            raise ArchicadError(f"Tapir {name} failed: {output.get('error')}")
        return output

    # -- element queries -----------------------------------------------------

    def get_selected_element_guids(self) -> list[str]:
        result = self.tapir("GetSelectedElements")
        return [e["elementId"]["guid"] for e in result.get("elements", [])]

    def get_all_element_guids(self) -> list[str]:
        result = self.api("API.GetAllElements")
        return [e["elementId"]["guid"] for e in result.get("elements", [])]

    # -- element edits -------------------------------------------------------

    def copy_elements(
        self, guids: Iterable[str], offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    ) -> None:
        """Duplicate elements via Tapir ``MoveElements`` with ``copy: true``."""
        x, y, z = offset
        self.tapir(
            "MoveElements",
            {
                "elementsWithMoveVectors": [
                    {
                        "elementId": {"guid": g},
                        "moveVector": {"x": x, "y": y, "z": z},
                        "copy": True,
                    }
                    for g in guids
                ]
            },
        )

    # -- properties ----------------------------------------------------------

    def get_user_property_guid(self, group: str, name: str) -> str:
        """Look up a user-defined property by its group and name."""
        result = self.api(
            "API.GetPropertyIds",
            {"properties": [{"type": "UserDefined", "localizedName": [group, name]}]},
        )
        entry = (result.get("properties") or [{}])[0]
        if "propertyId" not in entry:
            raise ArchicadError(
                f"User-defined property '{group} / {name}' was not found in this project."
            )
        return entry["propertyId"]["guid"]

    def set_string_property(self, guids: Iterable[str], property_guid: str, value: str) -> None:
        self.api(
            "API.SetPropertyValuesOfElements",
            {
                "elementPropertyValues": [
                    {
                        "elementId": {"guid": g},
                        "propertyId": {"guid": property_guid},
                        "propertyValue": {"value": value},
                    }
                    for g in guids
                ]
            },
        )
