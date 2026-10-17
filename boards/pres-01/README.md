# PRES-01 presentation board

A 600 × 750 mm portrait board for Capital Link Phomolong (Scheme B, with basement), built in
`CapitalLink-Presentation-Working.pln` through Tapir 1.7.0 on Archicad 29. The composition follows
the reference board: a dominant central render with the title above it, a narrow left column
(project information, design principles, round context diagram, section), five stacked plans on the
right, and a lower band with the site aerial, a street view, an axonometry and an interior panel.

## Files

| File | What it is |
| --- | --- |
| `board.json` | Page size, panel grid, palette pens, type sizes, text, and the source view or image for every panel |
| `prepare_images.py` | Crops the renders and the aerial photo to the panel proportions (never stretched) |
| `gdl/PRES_Image2D.xml` | Source of a tiny 2D picture object; compile it with `LP_XMLConverter xml2libpart` |

## Run it

```bash
python boards/pres-01/prepare_images.py "<Project-Workspace>" out/images
"C:/Program Files/GRAPHISOFT/Archicad 29/LP_XMLConverter.exe" xml2libpart -l UTF8 boards/pres-01/gdl/PRES_Image2D.xml out/PRES_Image2D.gsm
archicad-toolkit build-board boards/pres-01/board.json --assets out/images --gsm out/PRES_Image2D.gsm --manifest out/manifest.json --publish out/preview
```

Running it again rebuilds the board in place. Only elements listed in `manifest.json` *and* still on
the `PRES-01 Board` layer are deleted first, so anything added by hand on the layout survives.

## Source assignments

| Panel | Source |
| --- | --- |
| Hero | Render `Phomolong_Scheme_B_-_With_2K_20261016054242.jpg`, cropped to the central block and podium |
| Title, location | Editable text; location is a placeholder |
| Project information | Editable text; location, architect and area are placeholders |
| Design principles | Five placeholder rows with line icons (no principles were supplied) |
| Context circle | Aerial `SITE-PHOMOLONG_1.jpg`, circular crop around the site |
| Section | Linked drawing of "Building Section", 1:500, through the board view `PRES-01 Building Section` |
| Plans | Linked drawings at 1:750: Fifth, Third, Second, Ground Floor, Basement |
| Explanation | One paragraph from the model's storey structure, one placeholder for the project description |
| Site and context | Aerial `SITE-PHOMOLONG_1.jpg` |
| Street view | Render `2026_-_CAPITAL_LINK_CCCA.jpg` |
| Axonometry | Linked drawing of the 3D document "Axonometry", fitted to its slot (not to scale) |
| Interior | Placeholder: no interior render exists in the project files |

## What the builder changes in the project

- Adds subset **Presentation Boards**, master **PRES Master 600x750** and layout **PRES-01**.
- Adds layer **PRES-01 Board** and shows it in the `09 Layouting` combination.
- Adds layer combination **PRES-01 Presentation** and a View Map folder **PRES-01 Board Views** with
  copies of the six source views using it and the `09 Grayscale` pen set. It hides grids, markers,
  dimensions, zones, MEP, finishes and terrain, so the board drawings read as clean linework.
  The project's own views are not changed.
- Sets pens 241–246 of `03 Architectural 100` (previously unused placeholder pens) to the palette.
- Embeds the four prepared images and `PRES_Image2D.gsm` in the embedded library under `PRES-01/`.

## Known limits

- **Images:** Tapir 1.7.0 cannot place external images (Figures) on a layout, and the stock Picture
  object draws only a fill in 2D. `PRES_Image2D` draws the embedded picture with `PICTURE2`, at the
  exact slot size. To swap an image, replace the embedded file or change the object's `picName`.
- **Fonts:** Tapir has no font list, so every text uses the layout's default font. Pick a serif for
  the title and a sans-serif for the rest in the Text settings if wanted.
- **PDF:** the project's only layout publisher set (`1 - Layouts`) writes PNG, and Tapir cannot
  change a publisher set's format. Publish to PDF from Archicad's Publisher (or File > Save as PDF).
- **Preview resolution:** the PNG publisher set writes about 980 px wide, enough to check
  composition but not fine detail.
