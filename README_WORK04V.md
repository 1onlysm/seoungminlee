# WORK 04-V — NVDA mobile strike-map refinement

This is an offline UI refinement of the WORK 04-U dashboard. It does not alter option aggregation, snapshot evidence, or any market values.

## Mobile view

At viewport widths up to 700px, both strike charts open at $140–$220 so the documented concentration strikes are easier to inspect. The full 444-strike dataset remains embedded, and **Full strike range** returns to the source range. Desktop keeps the WORK 04-U initial range. **Initial view** restores the range appropriate to the current viewport.

The mobile chart uses a tighter SVG viewBox, fewer strike-axis labels, clearer axis text, touch-sized controls, and tap-to-select the closest existing strike. Dragging still pans, the zoom slider still zooms, Call/Put toggles remain, and the selected strike defaults to $170.

## Galaxy handoff checklist

Open the generated standalone HTML on the Galaxy device in its browser and check:
1. The initial range note reads **$140–$220** for each map.
2. The four observed totals, PCR, OI ratio, and 444-strike count remain unchanged.
3. Call/Put toggles, tap selection, drag pan, zoom, Initial view, Full strike range, and Center selected strike work.
4. The layout remains readable in portrait orientation.

The browser/device check is pending until this file is opened on a Galaxy device. The PNG preview is rendered from the verified data with Matplotlib; it is not a browser screenshot.

## Offline regression

```bash
python -m unittest discover -s tests -v
```
