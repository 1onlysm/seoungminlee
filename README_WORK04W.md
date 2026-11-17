# WORK 04-W — Galaxy chart readability hotfix

This offline-only hotfix keeps the verified NVDA dataset and aggregation unchanged.

- The mobile Volume and OI charts use one shared strike range. On a mobile viewport, both start at **$140–$220**; **Initial view** restores that range, and **Full strike range** shows the complete range. The OI panel now repeats the live shared range so it is clear when the charts have been panned or zoomed.
- The long rotated Y-axis title was removed from each SVG. Numeric Y-axis ticks remain; each panel title, subtitle, and metric badge identify the measure. The Volume subtitle still explains that Put bars are drawn below zero only for visual separation.
- All 444 strikes, original values, missingness, and the $170 selected-strike state are preserved.

## Offline regression

```bash
python -m unittest discover -s tests -v
```

Galaxy handoff: open the generated `nvda_options_dashboard.html` in the device browser, confirm both panels show `Shared strike view · $140–$220` on first load, then test **Initial view** and **Full strike range** from the Volume panel.

No live API, GitHub Actions, APK build, or external data access is part of this work.
