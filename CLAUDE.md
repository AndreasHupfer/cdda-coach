# CDDA Coach

Dieses Projekt stellt einen interaktiven Coach für **Cataclysm: Dark Days Ahead (CDDA)** bereit, der über Claude Code als Skill aufrufbar ist.

## Projektstruktur

```
cdda-coach/
├── CLAUDE.md
└── .claude/
    ├── settings.local.json
    ├── skills/
    │   ├── cdda-coach.md           # Haupt-Skill: Coach-Persona und Themenbereiche
    │   ├── obsidian-markdown.md    # Obsidian Flavored Markdown
    │   ├── obsidian-bases.md       # Obsidian Bases (.base Dateien)
    │   ├── obsidian-cli.md         # Obsidian CLI Interaktion
    │   ├── json-canvas.md          # JSON Canvas (.canvas Dateien)
    │   └── defuddle.md             # Web-Inhalte als Markdown extrahieren
    └── agents/
        └── cdda-lookup.md          # Sub-Agent: Recherche aus Online-Quellen
```

## Komponenten

### Skill: `cdda-coach`
Definiert die Coach-Persona. Wird über `/cdda-coach` aufgerufen. Gibt praxisnahe Ratschläge zu allen CDDA-Themen: Charakterbau, Überleben, Crafting, Fahrzeuge, Basenbau, Kampf, Spätspiel, Mechaniken.

### Agent: `cdda-lookup`
Recherche-Agent (Haiku-Modell) für faktische Spielinformationen. Wird vom Coach intern aufgerufen, wenn aktuelle oder detaillierte Daten gebraucht werden — Item-Stats, Trait-Details, Crafting-Rezepte, Mechanik-Erklärungen.

**Primäre Quellen des Agents:**
- https://cdda-guide.nornagon.net — interaktiver Item-Guide
- https://github.com/CleverRaven/Cataclysm-DDA — offizielles GitHub
- https://www.reddit.com/r/cataclysmdda/ — Community
- https://cataclysmdda.fandom.com — Fandom-Wiki

## Verwendung

```
/cdda-coach [optionale Frage oder Thema]
```

Der Coach antwortet auf Deutsch (außer der User schreibt Englisch) und ruft bei Bedarf den `cdda-lookup`-Agenten auf, um verlässliche, aktuelle Fakten aus dem Web zu beziehen.

### Obsidian Skills (von kepano/obsidian-skills)

| Skill | Aufruf | Zweck |
|-------|--------|-------|
| `obsidian-markdown` | `/obsidian-markdown` | Obsidian-spezifisches Markdown (Wikilinks, Callouts, Embeds) |
| `obsidian-bases` | `/obsidian-bases` | Datenbank-Views in `.base`-Dateien |
| `obsidian-cli` | `/obsidian-cli` | Vault-Interaktion per CLI, Plugin-Entwicklung |
| `json-canvas` | `/json-canvas` | Visuelle Canvas-Dateien (`.canvas`) |
| `defuddle` | `/defuddle` | Webseiten als sauberes Markdown extrahieren |

## Spielinstallation

| | Pfad |
|---|---|
| **Game-Verzeichnis** | `/home/andreas/opt/dda/game0` |
| **Save-Verzeichnis** | `/home/andreas/opt/dda/game0/save` |
| **Aktive Welt** | `Cowles` (`/home/andreas/opt/dda/game0/save/Cowles/worldoptions.json`) |

Beim direkten Bearbeiten von Weltoptionen immer die aktive `worldoptions.json` in diesem Pfad editieren.

## Konventionen

- Antwortsprache: Deutsch (default), Englisch wenn User Englisch schreibt
- Game-Begriffe (Traits, Encumbrance, Morale etc.) werden nicht übersetzt
- Referenzversion: CDDA 0.G / aktuelle Experimental-Builds
- `cdda-lookup` gibt maximal 300 Wörter zurück — kompakt und quellenbelegt
