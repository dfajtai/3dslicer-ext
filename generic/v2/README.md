# SpecimenViewer extension (generic engine + per-species modules)

## Miért lett kétrétegű?

Slicerben egy scripted modul saját neve/ikonja csak regisztrációkor
(`ScriptedLoadableModule.__init__`) állítható be - ezt runtime configváltással
nem lehet felülírni. Ha "minden faj kapja meg a saját nevét/ikonját a modul
listában", akkor minden fajnak **saját, regisztrált modulnak** kell lennie -
pont úgy, ahogy eddig is: `PigChunker`, `RabbitVertCount`, `DeerSegmentor`
külön modulok voltak.

Amit a generikus motor kivált, az nem "egy modul minden fajhoz", hanem **a
duplikált Widget/Logic/Specimen kódot** minden modul mögött. Így néz ki a
struktúra:

```
SpecimenViewerCommon/                  <- NEM Slicer modul, csak library
  GenericSpecimenEngine.py             <- Logic, GenericSpecimen, WidgetBase, batch_exporter

DeerSegmentor/                         <- saját Slicer modul: saját név, ikon
  DeerSegmentor.py                     <- ~50 soros wrapper, CONFIG_PATH-ot állít be
  Resources/UI/DeerSegmentor.ui
  Resources/Icons/DeerSegmentor.png    <- ide teszed a saját ikont
  Resources/deer_config.json           <- a study config

GenericSpecimenModule/                 <- "univerzális" modul, configváltó GUI-val
  GenericSpecimenModule.py
  Resources/UI/GenericSpecimenModule.ui
  config.json                          <- üres sablon

config_example_pig.json                <- PigChunker.py-nak megfelelő config (dokumentáció)
config_example_rabbit.json             <- RabbitVertCount.py-nak megfelelő config (dokumentáció)
config_example_dynamic_images.json     <- a dinamikus kép + preset feature bemutatása
```

Egy új faj = egy új mappa a `DeerSegmentor` mintájára: `.py` (kb. 50 sor,
csak title/icon/CONFIG_PATH), `.ui` (a generikus `.ui` átmásolva, `<class>`
átnevezve), `Resources/<species>_config.json`. **Nincs új Widget/Logic/
Specimen kód.**

A `GenericSpecimenModule` modul (a "Select .json file" sorral) arra jó, hogy
egy új configot ki tudj próbálni anélkül, hogy azonnal saját mappát/ikont
csinálnál neki - ha bevált, "kinövöd" egy saját wrapperré.

### Hogyan importálja a wrapper a közös engine-t

```python
_THIS_DIR = os.path.dirname(__file__)
_COMMON_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "SpecimenViewerCommon"))
if _COMMON_DIR not in sys.path:
    sys.path.append(_COMMON_DIR)
from GenericSpecimenEngine import GenericSpecimenModuleWidgetBase
```

Ez feltételezi, hogy `SpecimenViewerCommon` testvér mappa a modul mappájának
(pl. mindkettő közvetlenül az extension gyökere alatt van). Ha az extension
CMake-je máshova teszi, csak ezt a relatív path-ot kell igazítani.

## A `database.csv` / `preseg.csv` szerepe - változatlan

Ugyanaz, mint eddig: `key_columns` alapján párosítja a két csv-t, csak azok a
specimenek jelennek meg, amik mindkettőben szerepelnek.

**Bármelyik `database.csv` oszlop megjeleníthető és szerkeszthető** a
táblázatban - nem csak a `done`. Csak vedd fel a `table_columns` listába
(bármilyen sorrendben, akár csak részhalmazát a csv oszlopainak). A
visszaírás oszlopNÉV + a specimen valódi `row_index`-e alapján történik, nem
pozíció szerint - tehát biztonságos akkor is, ha a `table_columns` sorrendje
eltér a nyers csv oszlopsorrendjétől, és akkor is, ha a táblázatban a sorok
kulcs szerint rendezve jelennek meg, nem a csv sorrendjében.

## Config séma

```jsonc
{
  "study_dir": "...", "database_csv_path": "...", "preseg_csv_path": "...",
  "key_columns": ["ID"], "done_column": "done",
  "table_columns": ["ID", "comment", "done"],   // TETSZŐLEGES database.csv oszlop, nem csak done
  "output_dir_pattern": ["ID"],

  "images": [
    // A) explicit kép
    {
      "name": "background", "csv_column": "background",
      "path_pattern": "{ID}/{name}.nii.gz",   // fallback ha nincs csv_column érték
      "type": "volume", "role": "background", "required": true,
      "preset": "ct_default",                 // named preset (lásd lent)
      "opacity": 1.0                           // csak role=foreground/label esetén releváns
    },
    // B) dinamikus kép: annyi image nyílik meg, ahány preseg.csv oszlop illeszkedik
    //    ÉS nem üres AZ ADOTT specimennél. Név = oszlopnév (prefix/suffix vágható).
    {
      "csv_column_pattern": "^img_.*$",
      "name_strip_prefix": "img_",
      "type": "volume", "role": null, "required": false,
      "preset": "mri_default"
    }
  ],

  "presets": {
    "ct_default": { "window_level": {"min": -150, "max": 700} },
    "mri_default": { "window_level": {"auto": true}, "interpolate": true }
  },

  "visual_presets": [
    // csoportos szabályok, image-ek NEVÉRE illesztve (statikus VAGY dinamikus névre is),
    // list sorrendben cascade-elve (mint a CSS), a per-image preset UTÁN alkalmazva
    { "apply_to": ["dwi", "adc"], "color_table": "Rainbow" },
    { "apply_to_pattern": "^t[12]$", "color_table": "Grey", "window_level": {"min":0,"max":900} }
  ],

  "segmentation": {
    "enabled": true, "mode": "per_label_images", "reference_image": "mask",
    "segments": [
      { "name": "liver", "csv_column": "liver_path", "color": [0.8,0.1,0.1] },
      { "name": "tumor", "source": "empty", "color": [1,1,0] }   // nincs fájl, üres placeholder
    ],
    "output_filename": "segment.seg.nrrd", "opacity": 0.5
  },

  "landmarks": { "enabled": true, "csv_column": "markups_path", "writable": true, "color": [1,1,0] },
  "volume_rendering": { "enabled": false, "source_image": "background", "preset": "CT-Chest-Contrast-Enhanced" },
  "window_level": { "enabled": false, "min": -150, "max": 700 },

  "batch_export": {
    "enabled": true, "export_segments": true, "export_markups": true,
    "reference_image": "mask",
    "segments_filter": ["liver", "tumor"],   // opcionális: csak ezeket exportálja
    "output_dir": "results"                   // opcionális: közös mappa minden specimennek
  }
}
```

### Preset mezők (`presets.<name>` / image-en inline / `visual_presets` szabály)

| kulcs | hatás |
|---|---|
| `window_level: {min, max}` vagy `{auto: true}` | `SetWindowLevelMinMax` / `SetAutoWindowLevel` |
| `color_table` | Slicer color node ID vagy név (pl. `"vtkMRMLColorTableNodeRed"`, `"Grey"`, `"Rainbow"`) |
| `threshold: {min, max, apply}` | `SetThreshold` + `ApplyThresholdOn/Off` |
| `interpolate: true/false` | `SetInterpolate` |
| `opacity` | `role=foreground` -> slice compositing opacity; `role=label` -> label opacity |

Alkalmazási sorrend (utolsó nyer): named `preset`/`presets` -> az image
bejegyzésbe írt inline kulcsok -> a rá illeszkedő `visual_presets` szabályok
(lista sorrendben).

### Path feloldás (kép, szegmens, markup - mind ugyanaz)

1. Ha van `csv_column` és nem üres az adott specimennél -> azt használja.
2. Egyébként `path_pattern.format(...)`, elérhető kulcsok: `key_columns`
   értékei, a specimen `database.csv`/`preseg.csv` sorának minden oszlopa,
   image esetén `{name}`, szegmens esetén `{segment_name}`.
3. Dinamikus (`csv_column_pattern`) image-nél nincs `path_pattern` fallback -
   ha az oszlop üres az adott sorban, azt az image-et egyszerűen kihagyja.

### `segmentation.segments` (új, kifejezőbb forma)

Minden bejegyzés: `name`, és VAGY `csv_column` / `path_pattern` (fájlból
töltött, opcionálisan színezett szegmens), VAGY `"source": "empty"` (soha
nem próbál fájlt betölteni, mindig üres placeholder-t hoz létre - ez felel
meg a Deer `mask`/`non-liver`/`worm` szegmenseinek). `color: [r,g,b]`
mindkét esetben opcionális.

A régi, lapos `segment_names: [...]` (+ opcionális
`segment_name_csv_columns`) forma továbbra is működik (visszafelé
kompatibilis - ezt használja `config_example_pig.json` és
`config_example_rabbit.json`).

## A három lefedett történeti modul

| | PigChunker | RabbitVertCount | DeerSegmentor |
|---|---|---|---|
| kulcs | `ID, measurement` | `batch, ID, position` | `sid` |
| képek | background, mask | CT, mask | t1, t2, rel (egyedi preset: color table, threshold, window/level) |
| szegmentáció | egyedi label image-ekből, egységes | nincs | vegyes: 2 fájlból (színezve) + 3 üres placeholder |
| landmark | nincs | van, írható | nincs |
| volume rendering | nincs | van | nincs |
| batch export | csak segmentek | csak markup | segmentek, szűrve (`segments_filter`) |

Ezt fedi le: `config_example_pig.json`, `config_example_rabbit.json`,
`DeerSegmentor/Resources/deer_config.json`.

## Amit a generic verzió (még) leegyszerűsít

- `segmentation.mode` ténylegesen csak `"per_label_images"`-t buildel; ha az
  `output_filename` már létezik, azt tölti be (mindhárom eredeti modul "ha
  van mentve, azt töltsd be" logikájának felel meg).
- A Pig eredeti `Z:\` <-> NAS path csere logikája nincs benne - csak
  `study_dir` + relatív, vagy abszolút path.
- A Rabbit `final_save_dir`-je és a Deer külön `batch_exporter.py`-ja
  helyett egységesen `batch_export.output_dir` / `segments_filter`.

## Új study/faj felvétele

1. Másold le a `DeerSegmentor` mappát egy új névre (`XyzSegmentor`), töröld
   a `Resources/deer_config.json`-t, írj sajátot a study alapján.
2. `sed`-eld át a `.ui`-ban és a `.py`-ban a class/modul nevet.
3. Tegyél egy ikont a `Resources/Icons/`-ba (opcionális).
4. Regisztráld a modult a szokásos módon (CMakeLists / extension index).

Vagy: próbáld ki előbb a `GenericSpecimenModule`-lal (config picker-rel), és
csak ha bevált, "graduáld" saját wrapperré.
