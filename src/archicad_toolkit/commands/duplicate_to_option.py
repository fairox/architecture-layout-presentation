"""Duplicate the selected elements into a design-option variant.

Inspired by the Graphisoft wishlist post "Design options: duplicate selected
elements": select the elements that differ between options, run this command,
and get a tagged copy you can edit as the new variant.

How it works:
1. Read the current selection (Tapir ``GetSelectedElements``).
2. Snapshot all element GUIDs (``API.GetAllElements``).
3. Copy the selection in place, or by an optional offset (Tapir ``MoveElements``
   with ``copy: true``).
4. Snapshot again; the new GUIDs are the copies.
5. Write the option name into a user-defined string property on the copies,
   and on the originals when ``tag_originals`` is given, so graphic overrides,
   schedules and renovation-style filters can show one option at a time.

The property must already exist in the project (default group "Design Options",
name "Option").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from archicad_toolkit.client import ArchicadError, TapirClient

DEFAULT_PROPERTY_GROUP = "Design Options"
DEFAULT_PROPERTY_NAME = "Option"


@dataclass
class DuplicateResult:
    option: str
    source_guids: list[str]
    copy_guids: list[str]
    tagged_originals: str | None = None
    warnings: list[str] = field(default_factory=list)


def duplicate_to_option(
    client: TapirClient,
    option: str,
    *,
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    property_group: str = DEFAULT_PROPERTY_GROUP,
    property_name: str = DEFAULT_PROPERTY_NAME,
    tag_originals: str | None = None,
) -> DuplicateResult:
    """Copy the current selection and tag the copies as design option ``option``."""
    option = option.strip()
    if not option:
        raise ValueError("Option name must not be empty.")

    selected = client.get_selected_element_guids()
    if not selected:
        raise ArchicadError("Nothing is selected. Select the elements to duplicate first.")

    # Resolve the property before changing the model, so a missing property
    # fails without leaving untagged copies behind.
    property_guid = client.get_user_property_guid(property_group, property_name)

    before = set(client.get_all_element_guids())
    client.copy_elements(selected, offset)
    after = client.get_all_element_guids()
    copies = [g for g in after if g not in before]

    result = DuplicateResult(option=option, source_guids=selected, copy_guids=copies)
    if len(copies) != len(selected):
        result.warnings.append(
            f"Selected {len(selected)} elements but found {len(copies)} new ones; "
            "check the copies in Archicad."
        )

    if copies:
        client.set_string_property(copies, property_guid, option)
    if tag_originals:
        client.set_string_property(selected, property_guid, tag_originals)
        result.tagged_originals = tag_originals
    return result
