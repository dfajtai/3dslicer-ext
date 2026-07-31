# GenericSpecimenModule

Egyetlen, JSON-config-vezérelt 3D Slicer scripted modul, ami a `PigChunker` és
`RabbitVertCount` modulok közös logikáját váltja ki. Új faj / study típus
esetén **nem kell új `.py`-t írni**, csak egy `config.json`-t.

## Fájlok

```
GenericSpecimenModule/
├── GenericSpecimenModule.py          # a modul (Widget/Logic/Specimen)
├── Resources/UI/GenericSpecimenModule.ui
├── config.json                       # üres sablon (ezt tölti be alapból)
├── config_example_pig.json           # a PigChunker.py-nak megfelelő config
└── config_example_rabbit.json        # a RabbitVertCount.py-nak megfelelő config
```

A GUI-n a "Select .json file" gombbal bármikor másik configra lehet váltani
(pl. sertés vs. nyúl study), ekkor a DB/Preseg CSV mezők is automatikusan
frissülnek a config alapján.

## A `database.csv` és a `preseg.csv` szerepe (változatlan)

- `database.csv`: egy sor = egy specimen, ebben vannak a `key_columns`
  (azonosító oszlopok) és tetszőleges metaadat oszlopok (pl. `done`,
  mérési eredmények). Ez jelenik meg a táblázatban, és ebbe írható vissza a
  "done" jelölés / egyéb szerkeszthető oszlop.
- `preseg.csv` (img_paths): egy sor = egy specimen, ebben vannak a
  relatív útvonalak a képekhez/segmentekhez/landmarkokhoz.

A két táblát a `key_columns` alapján párosítja a modul (csak azok a
specimenek jelennek meg, amik mindkét csv-ben szerepelnek).

## Config séma

```jsonc
{
  "study_dir": "abszolút alap path, ehhez képest relatívak a preseg oszlopok / path_pattern-ek",
  "database_csv_path": "abszolút vagy study_dir-hez relatív path",
  "preseg_csv_path": "abszolút vagy study_dir-hez relatív path",

  "key_columns": ["ID", "measurement"],     // összetett kulcs oszlopnevei mindkét csv-ben
  "done_column": "done",                    // melyik oszlop jelzi, hogy kész-e
  "table_columns": ["ID", "measurement", "done"],  // ezek jelennek meg a GUI táblázatban (database.csv oszlopok)
  "output_dir_pattern": ["ID", "measurement"],     // ebből épül a study_dir/.../specimen kimeneti mappa

  "images": [
    {
      "name": "background",         // logikai név, ezzel hivatkozol rá (pl. role, reference_image, volume_rendering.source_image)
      "csv_column": "background",   // ha van ilyen oszlop a preseg.csv-ben és nem üres, ezt használja
      "path_pattern": "{ID}/{measurement}/{ID}-{name}.nii.gz",  // fallback, ha nincs csv_column érték; {key_columns}, {name}, és bármely db/preseg oszlop behelyettesíthető
      "type": "volume",             // "volume" | "labelmap"
      "role": "background",         // "background" | "label" | null -> slice viewer layer
      "required": true              // ha true és nem tölthető be -> hiba; ha false -> csendben kihagyja
    }
    // tetszőleges számú image ide felvehető
  ],
  "label_opacity": 0.15,

  "segmentation": {
    "enabled": true,
    "mode": "per_label_images",      // jelenleg támogatott mód: egyedi label-image-ekből építi fel a szegmentációt
    "reference_image": "mask",       // melyik images[].name legyen a geometria-referencia
    "segment_names": ["chunk", "body", "..."],
    "path_pattern": "{ID}/{measurement}/{ID}-{segment_name}.nii.gz",
    "segment_name_csv_columns": {    // opcionális: ha egy adott segmenthez külön preseg oszlop van
      "chunk": "chunk_path"
    },
    "output_filename": "segment.seg.nrrd",  // ha ez már létezik az out_dir-ben, azt tölti be a per-label build helyett
    "opacity": 0.5
  },

  "landmarks": {
    "enabled": true,
    "csv_column": "markups_path",    // preseg.csv oszlop a markups fájl path-jával
    "path_pattern": "{label}-markups.mrk.json",  // fallback, ha nincs csv_column érték
    "writable": true,
    "color": [1, 1, 0]
  },

  "volume_rendering": {
    "enabled": false,
    "source_image": "background",    // images[].name
    "preset": "CT-Chest-Contrast-Enhanced"
  },

  "window_level": {
    "enabled": false,
    "min": -150,
    "max": 700
  },

  "batch_export": {
    "enabled": true,
    "export_segments": true,
    "export_markups": true,
    "reference_image": "mask",       // segment export referencia volume (ha nincs megadva, a segmentation.reference_image-et használja)
    "output_dir": "results"          // opcionális: közös kimeneti mappa (study_dir-hez relatív vagy abszolút); ha nincs megadva, minden specimen a saját out_dir-jébe exportál
  }
}
```

### Path feloldás logika (minden path-nál ugyanaz)

1. Ha van `csv_column` és a preseg.csv-ben az adott specimen sorában nem
   üres az érték -> azt használja (relatív útvonalként, `study_dir`-hez
   képest, hacsak nem abszolút).
2. Egyébként a `path_pattern`-t próbálja `str.format(...)`-tal feloldani. A
   formázáshoz elérhető kulcsok: az összes `key_columns` érték, az adott
   specimen `database.csv` és `preseg.csv` sorának összes oszlopa, valamint
   image esetén `{name}`, segment esetén `{segment_name}`.

Ez pontosan azt a két mintát fedi le, ami a két eredeti modulban volt:
- Pig: a path-ok generált minta alapján épülnek fel (`{ID}-{name}.nii.gz`),
  a preseg.csv csak felülírja, ha meg van adva.
- Rabbit: a path-ok kizárólag a preseg.csv oszlopaiból jönnek
  (`img_path`, `mask_path`, `markups_path`), nincs generált minta.

## Amit a generic modul tud, amit az eredeti kettő külön-külön tudott

| Funkció | PigChunker | RabbitVertCount | Generic |
|---|---|---|---|
| tetszőleges számú kép | 2 (background, mask), hardcode | 2 (CT, mask), hardcode | `images[]`, tetszőleges szám |
| szegmentáció egyedi label-image-ekből | igen | nincs | `segmentation.mode = "per_label_images"`, opcionális |
| kész `.seg.nrrd` betöltése/mentése | igen | - | igen |
| landmarkok (markups) | nincs | igen | `landmarks`, opcionális |
| volume rendering | nincs | igen | `volume_rendering`, opcionális |
| window/level beállítás | nincs | igen | `window_level`, opcionális |
| batch export | igen (csak segmentek) | igen (csak markup) | `batch_export.export_segments` / `export_markups`, mindkettő opcionális, külön kimeneti mappával is |

## Amit érdemes tudni / amit a generic verzió leegyszerűsít

- A `segmentation.mode` jelenleg csak `"per_label_images"`-t implementál
  ténylegesen egyedi buildeléssel; ha `output_filename` már létezik, azt
  tölti be (ez felel meg mindkét eredeti modul "ha van mentett
  szegmentáció, azt töltsd be" logikájának).
- Az eredeti `PigChunker.fix_path`-ban volt egy `rel_paths` / hálózati
  meghajtó-csere (`Z:\` -> NAS path) logika. A generic verzió ezt nem
  reprodukálja (csak `study_dir` + relatív path, vagy abszolút path); ha ez
  kell, könnyen visszatehető a `_to_abs()` metódusba.
- A Rabbit modul saját `final_save_dir`-je (`root_path/results`, batch-tól
  függetlenül közös mappa) a `batch_export.output_dir` mezővel van lefedve.

## Új study felvétele

1. Másold le a `config.json`-t (vagy valamelyik példát) egy új névre.
2. Írd át a path-okat, `key_columns`-t, `table_columns`-t.
3. Add meg az `images`, illetve opcionálisan a `segmentation` /
   `landmarks` / `volume_rendering` / `window_level` / `batch_export`
   blokkokat a study igényei szerint.
4. Slicerben nyisd meg a modult, "Select .json file"-lal töltsd be az új
   configot, majd "Initialize Study".

Nincs szükség új `.py` vagy `.ui` fájlra egyik lépésnél sem.
