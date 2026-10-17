import pytest

from archicad_toolkit import ArchicadError, TapirClient
from fake_archicad import FakeArchicad


def test_tapir_commands_use_add_on_envelope():
    fake = FakeArchicad(elements=["a", "b"], selected=["b"])
    assert TapirClient(fake).get_selected_element_guids() == ["b"]
    request = fake.requests[0]
    assert request["command"] == "API.ExecuteAddOnCommand"
    assert request["parameters"]["addOnCommandId"] == {
        "commandNamespace": "TapirCommand",
        "commandName": "GetSelectedElements",
    }


def test_failed_command_raises():
    client = TapirClient(lambda req: {"succeeded": False, "error": {"message": "boom"}})
    with pytest.raises(ArchicadError, match="boom"):
        client.get_all_element_guids()


def test_failed_tapir_response_raises():
    def transport(req):
        return {
            "succeeded": True,
            "result": {"addOnCommandResponse": {"succeeded": False, "error": "nope"}},
        }

    with pytest.raises(ArchicadError, match="nope"):
        TapirClient(transport).get_selected_element_guids()


def test_copy_elements_sends_copy_flag_and_offset():
    fake = FakeArchicad(elements=["a"])
    TapirClient(fake).copy_elements(["a"], (1.0, 2.0, 0.0))
    item = fake.requests[0]["parameters"]["addOnCommandParameters"]["elementsWithMoveVectors"][0]
    assert item == {
        "elementId": {"guid": "a"},
        "moveVector": {"x": 1.0, "y": 2.0, "z": 0.0},
        "copy": True,
    }
    assert fake.elements == ["a", "copy-1"]


def test_missing_user_property_raises():
    with pytest.raises(ArchicadError, match="Design Options / Option"):
        TapirClient(FakeArchicad()).get_user_property_guid("Design Options", "Option")
