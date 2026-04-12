# CDDA Coach

Ein interaktiver Survival-Coach für **Cataclysm: Dark Days Ahead (CDDA)**, realisiert als Claude Code Skill. Der Coach liest das aktive Savegame direkt aus und gibt Ratschläge, Lageanalysen und Planungshilfe — im Immersiv-Stil, der nur zeigt was der Charakter wirklich weiß.

## Voraussetzungen

- [Claude Code](https://github.com/anthropics/claude-code) installiert
- Python 3.10+ mit `pyzstd`: `pip install pyzstd`
- Eine laufende CDDA-Installation mit einem Savegame

## Einrichtung

```bash
git clone <repo>
cd cdda-coach
cp .env.example .env
# CDDA_ROOT in .env auf das Spielverzeichnis setzen
```

`.env`:
```
CDDA_ROOT=/pfad/zur/cdda/installation
```

## Verwendung

Der Coach ist in diesem Projektverzeichnis immer aktiv — einfach `claude` starten und loslegen:

```bash
cd cdda-coach
claude
```

Dann Befehle als normalen Text eingeben (ohne `/`-Prefix, der wird von Claude Code abgefangen):

| Befehl | Funktion |
|--------|---------|
| `coach` | Volles Briefing: Status, Inventory, Karte, nächste Schritte |
| `status` | Aktueller Zustand in 3–5 Sätzen |
| `map` | Umgebungsbeschreibung im 20-Tile-Radius |
| `inv` | Inventory-Analyse mit Lücken |
| `threat` | Größte aktuelle Gefahr in einem Satz |
| `plan <ziel>` | Schritt-für-Schritt Plan |
| `craft <item>` | Crafting-Analyse |
| `loot <ort>` | Loot-Erwartung aus Char-Perspektive |
| `journal` | Tagebucheintrag → Obsidian |
| `mood` | Emotionaler Zustand aus Morale-Wert |
| `skill <name>` | Fähigkeits-Einschätzung |
| `cheat <frage>` | Volle Spielmechanik, Anti-Cheat aufgehoben |
| `help` | Befehlsübersicht |

## Projektstruktur

```
cdda-coach/
├── .env                        # CDDA_ROOT (nicht committet)
├── .env.example                # Template
├── CLAUDE.md                   # Coach-Persona und Projektdoku (immer geladen)
├── obsidian/                   # Obsidian-Vault für Session-Notizen
└── .claude/
    ├── tools/
    │   ├── cdda_reader.py      # Savegame-Reader (Status, Inventory, Skills, …)
    │   └── cdda_map_reader.py  # Map-Reader (Terrain, Furniture, ASCII-Karte)
    ├── skills/
    │   ├── cdda-coach.md       # Coach-Skill (Persona, Befehle, Ablauf)
    │   ├── obsidian-markdown.md
    │   ├── obsidian-bases.md
    │   ├── obsidian-cli.md
    │   ├── json-canvas.md
    │   └── defuddle.md
    └── agents/
        ├── cdda-lookup.md      # Recherche-Agent (Online-Quellen)
        └── obsidian-writer.md  # Obsidian-Schreib-Agent
```

## Tools

### `cdda_reader.py`

Liest Charakterdaten aus dem komprimierten Savegame (`.sav.zzip`).

```bash
python3 .claude/tools/cdda_reader.py <subcommand> [--world NAME] [--char NAME]
```

| Subcommand | Inhalt |
|------------|--------|
| `status` | HP, Hunger, Thirst, Stamina, Speed, Morale, Effekte, Position |
| `inventory` | Getragene Items und Inventory mit Tascheninhalten |
| `skills` | Skills mit Level > 0 |
| `traits` | Aktive Traits (ohne kosmetische) |
| `log` | Spiellog-Events |
| `diary` | Tagebucheinträge |
| `zones` | Zonen-Definitionen |
| `world` | Weltoptionen und Mods |
| `raw` | Vollständiger player-JSON-Block |

### `cdda_map_reader.py`

Liest den Map-Memory-Cache (mm1) und analysiert die gesehene Umgebung.

```bash
python3 .claude/tools/cdda_map_reader.py [--radius 20] [--ascii]
```

| Flag | Beschreibung |
|------|-------------|
| `--radius N` | Analyse-Radius in Tiles (Standard: 20) |
| `--ascii` | ASCII-Karte in der Ausgabe einschließen |
| `--ascii-width W` | Breite der ASCII-Karte (Standard: 60) |
| `--ascii-height H` | Höhe der ASCII-Karte (Standard: 30) |

Ausgabe enthält Terrain-Zählungen, Kategorien (Gebäude/Wald/Natur/Straße/Wasser), Richtungsübersicht und notable Furniture mit Distanz und Himmelsrichtung.

## Anti-Cheat-Modus

Der Coach weiß standardmäßig nur, was der Charakter weiß:

- ✅ Inventory, trainierte Skills, aktive Effekte, gesehene Karte
- ❌ Unbesuchte Gebäude, Monster-Stats, Loot-Tabellen, Spawn-Mechaniken

Mit `cheat <frage>` werden alle Einschränkungen für eine Antwort aufgehoben.

## Technisches

### Savegame-Format

CDDA speichert Savefiles als Zstandard-komprimierte JSON-Dateien in einem Custom-Container-Format (Skippable Frames + zstd-Payload). Die Tools scannen nach dem zstd-Magic (`\x28\xb5\x2f\xfd`) und dekomprimieren ab dort mit `pyzstd`.

Map-Memory-Dateien (`.mm1/*.zzip`) verwenden zusätzlich ein Zstandard-Dictionary (`mmr.dict`). Jede Datei enthält ein 8×8-Grid aus 12×12-Tile-Submaps, RLE-kodiert.

### Dateinamen

Charakternamen sind Base64-kodiert: `#TWF4IEhlbGZlbmJlcmdlcg==` → `Max Helfenberger`.
