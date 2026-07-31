# SpecimenViewer extension

```
SpecimenViewerCommon/GenericSpecimenEngine.py   <- shared logic, NOT a Slicer module itself
GenericSpecimenModule/                          <- prototyping module: config picker stays visible
DeerSegmentor/                                  <- example of a "graduated", named wrapper module
config_example_pig.json / _rabbit.json          <- reference configs, closest to the current pattern
config_example_dynamic_images.json              <- focused example of the dynamic-image feature
```

## Két lépcsős workflow

1. **Prototípus**: nyisd meg `GenericSpecimenModule`-t, "Select .json file"-lal
   tölts be / írj egy configot, "Initialize Study"-val teszteld. Nincs saját
   név/ikon, csak a config-géppel babrálsz.
2. **Graduálás**: ha bevált, csinálj belőle saját mappát a `DeerSegmentor`
   mintájára - egy ~50 soros `.py` (saját title + opcionális ikon +
   `CONFIG_PATH`), egy átnevezett `.ui`, egy saját `config.json`. Onnantól
   saját nevű/ikonú modul a Modules listában (ezt Slicer csak
   regisztrációkor engedi beállítani, ezért kell külön modul).

Wrapper import minta:
```python
_COMMON_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "SpecimenViewerCommon"))
sys.path.append(_COMMON_DIR)
from GenericSpecimenEngine import GenericSpecimenModuleWidgetBase

class XyzWidget(GenericSpecimenModuleWidgetBase):
    CONFIG_PATH = os.path.join(os.path.dirname(__file__), "Resources", "config.json")
    UI_RESOURCE = "UI/Xyz.ui"
```

## `database.csv` / `preseg.csv`

Változatlan: `key_columns` alapján párosítja a két csv-t. **Bármelyik
database.csv oszlop** felvehető a `table_columns`-ba, nem csak `done` -
szerkeszthető lesz a táblázatban, és oszlopNÉV + a specimen valódi
`row_index`-e alapján íródik vissza (nem pozíció szerint), tehát bármilyen
sorrendben/részhalmazban biztonságos.

## Config séma

Minden kép és szegmens ugyanazt a **defaults → preset → inline** felülírási
sorrendet követi (sima dict merge, utolsó nyer - nincs mintaillesztés, nincs
szabálylista):

```jsonc
{
  "study_dir": "...", "database_csv_path": "...", "preseg_csv_path": "...",
  "key_columns": ["ID"],                    // összetett kulcs mindkét csv-ben
  "table_columns": ["ID", "comment", "done"],  // database.csv oszlopok a táblázatban (comment IS csak példa - amire szükséged van)
  "output_dir_pattern": ["ID"],              // ebből épül a kimeneti mappa

  "defaults": {
    "image":   { "type": "volume", "required": false /* stb: bármi, amit minden image örököljön */ },
    "segment": { /* bármi, amit minden segment örököljön, pl. közös opacity-szerű mező */ }
  },
  "presets": {
    "ct_default": { "window_level": {"min": -150, "max": 700} }
  },

  "images": [
    // A) explicit kép: defaults.image -> presets.<preset> -> ez a dict, ebben a sorrendben
    { "name": "background", "csv_column": "background", "role": "background",
      "path_pattern": "{ID}/{name}.nii.gz",   // csak ha nincs csv_column érték
      "preset": "ct_default", "type": "volume", "required": true },

    // B) dinamikus kép: annyi nyílik meg, ahány preseg.csv oszlop illeszkedik ÉS
    //    nem üres AZ ADOTT specimennél. Név = oszlopnév (prefix/suffix vágható).
    { "pattern": "^seq_.*$", "strip_prefix": "seq_", "preset": "ct_default" }
  ],

  "segmentation": {
    "enabled": true,
    "reference_image": "mask",
    "path_pattern": "{ID}/{segment_name}.nii.gz",   // default naming, felülírható segmenenként
    "segments": [
      { "name": "liver", "csv_column": "liver_path", "color": [0.8,0.1,0.1] },  // source: "file" (default)
      { "name": "tumor", "source": "empty", "color": [1,1,0] }                   // sose próbál fájlt nyitni
    ],
    "output_filename": "segment.seg.nrrd", "opacity": 0.5
  },

  "landmarks": { "enabled": true, "csv_column": "markups_path", "writable": true, "color": [1,1,0] },
  "volume_rendering": { "enabled": false, "source_image": "background", "preset": "CT-Chest-Contrast-Enhanced" },
  "window_level": { "enabled": false, "min": -150, "max": 700 },  // globális, MINDEN betöltött volume-ra (nem csak image-enkénti preset)

  "batch_export": {
    "enabled": true, "export_segments": true, "export_markups": true,
    "reference_image": "mask", "segments_filter": ["liver", "tumor"], "output_dir": "results"
  }
}
```

### Preset mezők

| kulcs | hatás |
|---|---|
| `window_level: {min,max}` | `SetWindowLevelMinMax(min,max)` - tartomány |
| `window_level: {window,level}` | `SetWindowLevel(window,level)` - ablakszélesség + közép (**nem ugyanaz**, mint a min/max forma - pl. `{window:1,level:2}` kb. az 1.5-2.5 tartományt jeleníti meg, nem az 1-2-t) |
| `window_level: {auto:true}` | `SetAutoWindowLevel(1)` |
| `color_table` | Slicer color node ID vagy név (`"vtkMRMLColorTableNodeRed"`, `"Grey"`, `"Rainbow"`, ...) |
| `threshold: {min,max,apply}` | `SetThreshold` + `ApplyThresholdOn/Off` |
| `interpolate: true/false` | `SetInterpolate` |
| `opacity` | `role=foreground`/`label` esetén a slice compositing opacity |

Csoportos kinézethez (több kép ugyanazzal a preset-tel): adj nekik ugyanazt
a `"preset": "név"`-et - a dinamikus (`pattern`) bejegyzés is egy preset-et
kap, ami minden belőle generált képre vonatkozik.

### `segmentation.segments[]`

- `name` (kötelező), `color: [r,g,b]` (opcionális mindkét forrásnál).
- `"source": "file"` (alapértelmezett): `csv_column` vagy (saját / a
  `segmentation.path_pattern` default) `path_pattern` alapján tölt; ha egyik
  sem ad path-ot, vagy a fájl nem nyitható, üres placeholder segmentet hoz
  létre helyette (figyelmeztetéssel).
- `"source": "empty"`: sosem próbál fájlt keresni/nyitni, mindig üres
  placeholder (pl. kézzel szegmentálandó struktúra).

Nincs visszafelé kompatibilitás a régi, lapos `segment_names` formával - ha
korábbi Pig/Rabbit/Deer configot migrálsz, írd át `segments: [...]`-re
(lásd a három példa configot).

## A három referencia config

| | Pig | Rabbit | Deer |
|---|---|---|---|
| kulcs | `ID, measurement` | `batch, ID, position` | `sid` |
| képek | background, mask (közös `defaults.image.path_pattern`) | CT, mask (path csak csv-ből) | t1, t2, rel (`rel`-nek saját preset: color table + threshold + window/level) |
| szegmentáció | 7 segment, közös `segmentation.path_pattern` | nincs | vegyes: 2 fájlból színezve + 3 `source:"empty"` placeholder |
| landmark | nincs | van, írható | nincs |
| volume rendering | nincs | van | nincs |
| globális window/level (`cfg.window_level`, MINDEN betöltött volume-ra) | nincs | van (-150/700, min/max forma) | nincs |
| kép-specifikus window/level (image `preset`-en keresztül, csak arra a képre) | nincs | nincs | van (`rel`: `{window:1, level:2}`, width/center forma) |
| batch export | segmentek | csak markup, közös `output_dir` | segmentek, `segments_filter`-rel szűrve |

Fontos: a két window/level mechanizmus **különböző dolog**, és a kép-specifikus forma két, egymással nem felcserélhető Slicer API-t fed le (`{min,max}` vs `{window,level}` - lásd fentebb a preset táblázatot). Az eredeti Deer kód `SetWindowLevel(1,2)`-t hívott, ami a `{window:1, level:2}` formának felel meg, NEM `{min:1, max:2}`-nek.

## Új study/faj felvétele

1. Másold le a `DeerSegmentor` mappát, cseréld a title/CONFIG_PATH-ot a
   `.py`-ban, `sed`-eld át a `<class>`-t a `.ui`-ban.
2. Írj egy configot a fenti séma alapján (indulj a hozzád legközelebb álló
   referenciából).
3. Vagy: próbáld ki előbb `GenericSpecimenModule`-lal, mielőtt saját mappát
   csinálnál.
