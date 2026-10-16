# architecture-layout-presentation

An Archicad automation toolkit built on [Tapir](https://github.com/ENZYME-APD/tapir-archicad-automation)
and the Archicad JSON API. It covers two jobs:

- **Layout and presentation sets:** producing and keeping consistent the layouts used to present a scheme.
- **Design options:** keeping option variants side by side in one model.

The guiding use case is the Graphisoft wishlist post
[Design options: duplicate selected elements](https://community.graphisoft.com/t5/Wishlist/Design-options-duplicate-selected-elements/idi-p/717764).
You select the elements that change between options, run one command, and get a tagged copy to develop as the next option.

## Status

This is an early scaffold. It ships one command, `duplicate-to-option`. Layout and presentation commands come next.

## Requirements

- Archicad 26 or later with the Tapir add-on installed. Archicad listens for JSON commands on `http://127.0.0.1:19723`.
- Python 3.10+. The package has no runtime dependencies.
- A user-defined **string** property in the project. By default its group is `Design Options` and its name is `Option`. Choose a classification or element type availability that covers the elements you will duplicate.

## Install

```bash
pip install -e ".[dev]"
```

## Commands

### `duplicate-to-option`

Copies the selected elements and writes the option name into the option property on the copies.

```bash
# Copy the selection in place as "Option B", and mark the originals as "Option A"
archicad-toolkit duplicate-to-option "Option B" --tag-originals "Option A"

# Copy 20 m along X so both options sit side by side
archicad-toolkit duplicate-to-option "Option B" --offset 20 0 0
```

Options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--offset X Y Z` | `0 0 0` | Move the copies by this vector, in metres |
| `--tag-originals NAME` | none | Also tag the selected originals |
| `--property-group` | `Design Options` | Group of the option property |
| `--property-name` | `Option` | Name of the option property |
| `--url` | `http://127.0.0.1:19723` | Archicad JSON API address |

Once elements are tagged, use the property in Graphic Overrides, schedules or Find & Select to show or isolate one option at a time.

The command works in these steps:

1. Read the selection with Tapir `GetSelectedElements`.
2. Copy it with Tapir `MoveElements`, with `copy: true`.
3. Find the new elements by comparing `API.GetAllElements` before and after the copy.
4. Tag the copies with `API.SetPropertyValuesOfElements`.

It checks for the option property before copying anything, so an empty selection or a missing property leaves the model untouched.

## Layout

```
src/archicad_toolkit/
  client.py                     thin JSON API / Tapir client with an injectable transport
  commands/duplicate_to_option.py
  cli.py                        archicad-toolkit entry point
tests/
  fake_archicad.py              in-memory Archicad + Tapir used as the transport
```

## Testing without Archicad

`TapirClient` sends every request through a *transport*, which is a function from a request dict to a response dict.
The tests plug in `tests/fake_archicad.py`, an in-memory model that answers the same commands. Archicad never needs to be running.

```bash
python -m pytest
```

To add a command, write a function that takes a `TapirClient`, then teach `FakeArchicad` any new commands it sends.
CI runs the suite on Python 3.10 to 3.13.
