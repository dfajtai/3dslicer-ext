# GenericSpecimenManager

Egyetlen Slicer modul, JSON-configgal vezérelve. Nincs species-enkénti
Python modul - egy config.json ír le egy study-t (képek, szegmensek,
landmarkok, batch export, stb.), és a modul azt tölti be.

## Fájlstruktúra (a repóban)

```
GenericSpecimenManager/GenericSpecimenManager/GenericSpecimenManager/
├── GenericSpecimenManager.py        <- a Slicer modul (title/icon, Widget/Logic wiring)
├── Config/                          <- study configok (pig_config.json, rabbit_config.json, deer_config.json, ...)
├── Examples/                        <- referencia/dokumentációs célú, NEM regisztrált wrapper-példák
│   ├── DeerSegmentor.py / PigChunker.py / RabbitVertCount.py
│   └── README.md
├── Resources/
│   ├── ConfigModel.py               <- dataclass-ok: StudyConfig és a séma többi része
│   ├── GenericSpecimenEngine.py     <- a tényleges logika (Logic, GenericSpecimen, Widget base, batch export)
│   ├── ConfigEditor.py              <- "Config Editor..." gomb mögötti dialógus
│   ├── Icons/GenericSpecimenManager.png
│   └── UI/GenericSpecimenManager.ui
└── Testing/
```

`GenericSpecimenManager.py` a `Resources` mappát teszi fel a `sys.path`-ra,
és `from Resources.GenericSpecimenEngine import GenericSpecimenManagerWidgetBase`
importtal éri el a logikát. A négy fájl külön felelőssége:

| fájl | felelősség |
|---|---|
| `GenericSpecimenManager.py` | a Slicer modul regisztrációja (title, icon, `CONFIG_PATH`) |
| `Resources/ConfigModel.py` | a config.json típusos, attribútum-eléréses reprezentációja |
| `Resources/GenericSpecimenEngine.py` | Logic, `GenericSpecimen` (egyed betöltés/mentés/bezárás), Widget-alaposztály, batch export |
| `Resources/ConfigEditor.py` | GUI a config.json összerakásához kézi JSON-szerkesztés nélkül |

## ConfigModel - típusos config, nem `.get()`-lánc

A régi `cfg["segmentation"].get("segments", [])`-szerű hozzáférés helyett
`cfg.segmentation.segments`. Két csoport van:

- **Section dataclass-ok** (`StudyConfig`, `SegmentationConfig`,
  `LandmarksConfig`, `VolumeRenderingConfig`, `GlobalWindowLevelConfig`,
  `BatchExportConfig`, `SegmentEditorConfig`, `BrushConfig`,
  `BatchModeConfig`, `DefaultsConfig`) - egy jelentés, egy hely a sémában,
  egyszer épülnek fel a nyers dict-ből.
- **Override dataclass-ok** (`ImageConfig`, `SegmentConfig`, `WindowLevel`,
  `Threshold`) - minden mező `Optional`, alapból `None` ("nincs megadva").
  Ugyanez a forma szolgál `defaults.image`-hez, `presets[name]`-hez ÉS egy
  konkrét `images[]` bejegyzéshez is; a `merge_image_overrides()` /
  `merge_segment_overrides()` rétegzi őket (defaults -> preset -> saját
  mező, az utolsó nem-`None` érték nyer). Csak a felhasználás helyén kerül
  szemantikai alapérték (`img_cfg.type or "volume"`), így a merge sosem
  keveri össze "nincs megadva"-t a dataclass saját defaultjával.

`load_config(path) -> StudyConfig` tölti be és parse-olja a JSON-t.

## Config séma - változatlan JSON kulcsok, új top-level: `batch_mode`

A korábbi séma (images, defaults/presets, segmentation.segments,
landmarks, volume_rendering, window_level, batch_export, segment_editor)
nem változott JSON-szinten. Új blokk:

```jsonc
"batch_mode": {
  "enabled": true,
  "column": "batch"        // database.csv oszlop, ami szerint csoportosít/szűr
}
```

Ha `batch_mode.enabled`, a GUI-n "Initialize Study" után megjelenik egy
batch-választó combo box (`cmbBatch`), ami a `column` oszlop egyedi
értékeivel töltődik fel ("(all)" + az összes érték). Váltáskor újraszűri a
specimen táblázatot. **Aktív (betöltött) specimen mellett a váltás
tiltott** - előbb be kell zárni.

Batch-enkénti export:
```jsonc
"batch_export": {
  "enabled": true,
  "export_segments": true,
  "per_batch_subfolder": true    // out_dir/<batch_érték>/... mappákba exportál, nem laposan
}
```

## Config Editor

"Config Editor..." gomb minden modul GUI-jában (Study settings alatt).
Önálló, nem-modális ablak, ami **automatikusan a főmodulban éppen betöltött
configgal nyílik meg** (ha van ilyen).

Fülekre bontva gyakorlatilag a teljes séma szerkeszthető:

| fül | tartalom |
|---|---|
| General | paths, key/table/output-dir columns, batch_mode |
| Images | táblázat (name, csv_column, pattern/strip, type, role, required, preset, opacity, color_table) + "Edit advanced..." popup a window_level/threshold/interpolate-hez |
| Segmentation | enabled, reference_image, path_pattern, output_filename, segments táblázat (name, source, csv_column, path_pattern, szín-választó) |
| Landmarks | enabled, csv_column, path_pattern, template_path, writable, color |
| Volume rendering | enabled, source_image, preset |
| Window/level | globális (minden betöltött volume-ra) enabled/min/max |
| Batch export | enabled, export_segments/markups, reference_image, segments_filter, output_dir, per_batch_subfolder |
| Segment editor | overwrite_mode, brush (shape/diameter/relative), active_effect, raw attributes (JSON) |
| Defaults / Presets | `defaults.image`, `defaults.segment`, `presets` - nyers JSON mezőkként, tooltippel + "Show example presets..." gombbal (5 kész, másolható preset: ct_soft_tissue, ct_bone, mri_auto, red_overlay, label_overlay) |

**Munkafolyamat-gombok:**
- **New** - üres formra vált; ha piszkos az aktuális állapot, Save/Discard/Cancel kérdés.
- **Load from file...** - tallózható betöltés; ugyanígy rákérdez a nem mentett módosításokra előtte.
- **Help** - görgethető súgó ablak a kevésbé nyilvánvaló mezőkről (pl. `segmentation.path_pattern` placeholderek, `images[].pattern` dinamikus kép-logika, preset merge sorrend, batch mód, stb.).
- Minden nem-nyilvánvaló mezőn **tooltip** van (hover).

A form minden mezőn figyeli a változást (`_dirty` flag), a címsorban `*`
jelzi, ha van nem mentett módosítás; bezáráskor (gomb vagy ablak "X") is
rákérdez, ha kell.

**Javított hiba**: a "Close" gomb korábban beragadhatott (nem záródott be
az ablak). Oka: a `closeEvent`-ben hívott mentés-rákérdező logika egy
esetleges kivétele PythonQt-ban csendben elnyelődhet egy C++-ból hívott
virtuális metóduson belül, így az `event.accept()` sosem futott le. A
`closeEvent` mostantól try/except-be csomagolva - bármilyen belső hiba
esetén is bezáródik az ablak, csak logol egy üzenetet.

Amit még mindig kézi JSON-szerkesztés igényel: nagyon egyedi kombinációk,
amikre a Defaults/Presets fülön túl nincs dedikált mező (ez a tervezett
határ, nem hiba).

## `segment_editor` - a brush-alkalmazás felülvizsgálva

Két hibaosztályt találtunk éles használatban:

1. **Semmi nem érvényesült** (se `overwrite_mode`, se brush méret/alak).
2. **GUI-scene desync**: a méret-csúszka folyton visszaugrott egy értékre,
   a widget és a node kapcsolata összezavarodott.

Mindkettő ugyanabból a két okból fakadt:

- A node-ot **scene-szintű kereséssel** (`GetFirstNodeByClass`) szereztük
  meg, ami NEM garantáltan ugyanaz a node, amihez a ténylegesen látható
  Segment Editor widget kötve van (pl. a mi saját get-or-create default
  template node-unk is `vtkMRMLSegmentEditorNode` típusú - kettő van a
  jelenetben, a keresés bármelyiket visszaadhatja). Ha a rossz node-ot
  módosítottuk, a widget nem is látta a változást -> "semmi nem
  érvényesült".
- Egyetlen `processEvents()` hívás **nem garantálta**, hogy a Segment
  Editor widget (spinbox-ok, checkbox-ok, jel-nyél bekötések) már teljesen
  felépült, mire hozzányúltunk a node-hoz. Ha a widget csak UTÁNUNK kötötte
  be a saját signal/slot-jait, azok a MI módosításunk előtti állapotot
  cache-elték - onnantól a widget "visszaírta" a régi értéket minden
  interakciónál, mintha versenyeznénk a felhasználóval.

**Javítás** (`GenericSpecimenEngine._configure_segment_editor` /
`_apply_segment_editor_config`):

- A node-ot a **widget-től magától** kérjük (`segmentEditorWidget.mrmlSegmentEditorNode()`),
  nem scene-wide kereséssel - garantáltan ugyanaz, amit a látható GUI használ.
- A configurálást **nem szinkron** módon, hanem `qt.QTimer.singleShot(0, ...)`-tal
  a következő event loop ciklusra halasztjuk `selectModule("SegmentEditor")`
  után - így a widget teljesen felépül, mielőtt hozzányúlnánk.
- A módosítások után explicit **`effect.updateGUIFromMRML()`**-t hívunk az
  aktív Paint effect-en, hogy a spinbox/checkbox hivatalos frissítési úton
  szinkronizálódjon a node-dal - ez szünteti meg a "visszaugrás" tünetet,
  mert nem hagyjuk a widget cache-elt állapotát elavulva a node mögött.

Ez élő Slicer nélkül, kód-review alapján a legvalószínűbb ok/javítás -
ha továbbra is gond van, a legjobb diagnosztikai lépés: a Python
konzolon nézd meg `segmentEditorWidget.mrmlSegmentEditorNode() is segmentEditorNode`
(ugyanaz-e a node, amit a GUI ténylegesen használ), illetve hogy a
`Paint,BrushAbsoluteDiameter` attribútum értéke a node-on tényleg a várt-e
közvetlenül a beállítás után.

## Batch mód + aktív specimen kezelése

Batch váltás közben aktív specimen esetén hibaüzenet és a combo box
visszaáll az előző értékre - nincs félbehagyott állapot (a specimen betöltve
marad, a táblázat nem változik, amíg be nem zárod).

## Új study felvétele

1. `Config/<species>_config.json` a séma alapján.
2. GUI-n `Select .json file` -> "Initialize Study", vagy a Config Editor-ral
   generáld a kiindulást.
3. Ha végleges: opcionálisan tedd bele az `Examples/` mappába egy rövid,
   referencia jellegű wrapper-t (nem kötelező - ott lévő fájlok nincsenek
   CMake-be regisztrálva, csak dokumentálják, hogyan nézne ki egy saját
   nevű/ikonú modul, ha valaha külön kellene).
