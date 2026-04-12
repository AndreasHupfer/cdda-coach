# Survival Hardcore

Eine Welt für erfahrene Überlebende. Knapper Loot, schnell mutierende Zombies und kurze
Jahreszeiten erzwingen konsequentes Ressourcenmanagement und langfristige Planung.

## Spielgefühl

Kein Ausrüstungsüberschuss. Jede Dose Bohnen zählt, jeder Wintereinbruch ist eine echte
Bedrohung. Städte sind gefährlich — wer zu lange wartet, trifft auf Hordes aus evovierten
Zombies. NPCs und Fraktionen spielen eine aktive Rolle, da Kooperation manchmal überlebenswichtig ist.

## Schwierigkeit

**Mittel-Schwer** — geeignet für Spieler mit Grundkenntnissen in Crafting und Kampf.

## Konfiguration

```json
{
  "SPAWN_DENSITY": 1.5,
  "ITEM_SPAWNRATE": 0.6,
  "EVOLUTION_INVERSE_MULTIPLIER": 0.5,
  "SEASON_LENGTH": 14,
  "ETERNAL_SEASON": false,
  "SPAWN_CITY_HORDE_SCALAR": 100.0,
  "SPAWN_ANIMAL_DENSITY": 1.2,
  "NPC_SPAWNTIME": 1.5
}
```

| Key | Wert | Effekt |
|---|---|---|
| `SPAWN_DENSITY` | 1.5 | 50% mehr Zombies |
| `ITEM_SPAWNRATE` | 0.6 | 40% weniger Loot |
| `EVOLUTION_INVERSE_MULTIPLIER` | 0.5 | Doppelt so schnelle Mutation |
| `SEASON_LENGTH` | 14 | 14 Tage pro Jahreszeit |
| `SPAWN_CITY_HORDE_SCALAR` | 100.0 | Größere Stadthordes |
| `SPAWN_ANIMAL_DENSITY` | 1.2 | Etwas mehr Wild |
| `NPC_SPAWNTIME` | 1.5 | Mehr NPCs / Fraktionsaktivität |

## Installation

1. Im Spiel eine neue Welt erstellen (Name z.B. `SurvivalHardcore`)
2. `worldoptions.json` aus diesem Verzeichnis kopieren nach:

```
~/.local/share/cataclysm-dda/save/SurvivalHardcore/worldoptions.json
```

3. Welt neu laden — Einstellungen sind aktiv.

## Empfohlene Mods

| Mod | Effekt | Status |
|---|---|---|
| **No Hope** | Knapperer Loot, härtere Gegner | Integriert — vor Benutzung testen (Compat-Issues in neuen Experimentals) |
| **Survivor Bias** | Feinere Charakter-Setup-Optionen | Integriert, stabil |
| **Aftershock** | Neue Biome, Fraktionen, Sci-Fi-Layer | Extern, aktiv gepflegt |

## Anpassungen

**Zu schwer?**

```json
"ITEM_SPAWNRATE": 0.8,
"SPAWN_DENSITY": 1.2,
"EVOLUTION_INVERSE_MULTIPLIER": 1.0
```

**Noch härter?**

```json
"ITEM_SPAWNRATE": 0.4,
"SPAWN_DENSITY": 2.0,
"SEASON_LENGTH": 9
```
