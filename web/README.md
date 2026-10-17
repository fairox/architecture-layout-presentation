# Board Configurator

A static web app for laying out an Archicad presentation board. It edits the same
config that `archicad-toolkit build-board` reads (see `boards/pres-01/board.json`),
shows a live preview of the board, and exports a **board file** that the
**Tapir script** `archicad/BuildBoard.py` builds in Archicad.

The page never talks to Archicad. Everything stays in the browser (the config in
`localStorage`, pictures in IndexedDB) until you download the board file and run
the script on the computer where Archicad runs.

## What you can change

| Tab | Settings |
| --- | --- |
| Page | Layout ID, name, subset, master, layer, publisher set; page size (presets or custom, optionally scaling the layout with it); border; panel grid (columns, rows, gutter, snap step) |
| Style | Palette pens (colour, pen number, weight), pen table, type sizes, preview fonts |
| Text | Title, location, project information, design principles, explanation, credit, captions, placeholders |
| Sources | Pictures (drop a render or photo, set focus, zoom and shape) and drawings (source view id, scale or fit, model clip, caption); board view settings |
| Build | Checks, picture resolution, downloads, and the command to run |

On the board: drag any panel, picture, drawing slot, placeholder or caption; drag a
handle to resize (Shift keeps proportions); Alt skips snapping; arrow keys nudge.
Moving a panel moves what is inside it. Ctrl+Z / Ctrl+Shift+Z undo and redo.

## Build in Archicad

```bash
python BuildBoard.py PRES-01.board.json --check     # validate and unpack, no Archicad needed
python BuildBoard.py PRES-01.board.json --publish   # build or rebuild, then publish a preview
```

The script validates the file, unpacks the cropped pictures, compiles the
`PRES_Image2D` picture object with Archicad's `LP_XMLConverter`, builds the layout
and reads every placement back. Work files go to `Documents/Archicad Boards/<layout id>/`.
Keep that folder: its `manifest.json` is how a rerun replaces only its own elements.
If a board was built earlier with `archicad-toolkit build-board`, pass that run's
manifest once with `--manifest`. Pictures not inside the board file can come from
`--assets <folder>`.

## Develop

No build step. Serve the folder and open it:

```bash
python3 -m http.server 8000 -d web
cd web && npm test            # model and preview tests (node --test)
python tools/build_web.py     # regenerate archicad/BuildBoard.py and presets/ after editing the package or boards/
```

`archicad/BuildBoard.py` and `presets/` are generated; CI fails if they are stale.

## Deploy on Vercel

Import the repository in Vercel and set **Root Directory** to `web`, **Framework
Preset** to *Other*, with no build command and no output directory. `vercel.json`
sets the security headers (a strict Content-Security-Policy: the page loads only
its own files) and serves the Tapir script as a download.
