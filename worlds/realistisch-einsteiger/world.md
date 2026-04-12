# Realistisch Einsteiger

Eine Welt für Neulinge, die das echte CDDA-Feeling erleben wollen — ohne sofort überrannt zu werden.
Normale Zombie-Dichte, etwas mehr Loot, langsame Mutation und lange Jahreszeiten geben Zeit, das Spiel
zu verstehen, ohne auf Realismus zu verzichten.

## Spielgefühl

Die Welt fühlt sich wie eine echte Apokalypse an: Städte sind gefährlich, Ressourcen endlich,
Winter kommt. Aber der Rhythmus ist vergebend — Zombies mutieren langsam, die Jahreszeiten lassen
Planungszeit, und ein paar Extra-Dosen Konserven sorgen dafür, dass ein Fehler nicht sofort das Ende
bedeutet. NPCs tauchen auf und können als Verbündete oder Händler nützlich sein.

## Schwierigkeit

**Einsteiger-Freundlich** — geeignet für Spieler ohne Vorkenntnisse in Crafting, Hunger/Durst-Management
und Kampfmechaniken.

## Konfiguration

```json
{
  "SPAWN_DENSITY": 1.0,
  "ITEM_SPAWNRATE": 1.2,
  "EVOLUTION_INVERSE_MULTIPLIER": 2.0,
  "SEASON_LENGTH": 28,
  "ETERNAL_SEASON": false,
  "SPAWN_CITY_HORDE_SCALAR": 50.0,
  "SPAWN_ANIMAL_DENSITY": 1.0,
  "NPC_SPAWNTIME": 2.0
}
```

| Key | Wert | Effekt |
|---|---|---|
| `SPAWN_DENSITY` | 1.0 | Standard-Zombiedichte — realistisch, nicht erdrückend |
| `ITEM_SPAWNRATE` | 1.2 | 20% mehr Loot — Puffer für Anfängerfehler |
| `EVOLUTION_INVERSE_MULTIPLIER` | 2.0 | Doppelt so langsame Mutation — Zeit zum Lernen |
| `SEASON_LENGTH` | 28 | 28 Tage pro Jahreszeit — genug Zeit für Wintervorbereitung |
| `SPAWN_CITY_HORDE_SCALAR` | 50.0 | Halbierte Stadthordes — Städte bleiben gefährlich, aber erkundbar |
| `SPAWN_ANIMAL_DENSITY` | 1.0 | Standard-Wildtiere — Jagd als Nahrungsquelle funktioniert |
| `NPC_SPAWNTIME` | 2.0 | Regelmäßige NPCs — potenzielle Verbündete und Händler |

## Installation

1. Im Spiel eine neue Welt erstellen (Name z.B. `RealistischEinsteiger`)
2. `worldoptions.json` aus diesem Verzeichnis kopieren nach:

```
~/.local/share/cataclysm-dda/save/RealistischEinsteiger/worldoptions.json
```

3. Welt neu laden — Einstellungen sind aktiv.

## Tipps für Einsteiger

- **Erste Nächte:** Nicht in der Stadt schlafen. Ein Haus am Stadtrand oder eine Farm ist sicherer.
- **Lärm vermeiden:** Schüsse ziehen Zombies von weitem an. Nahkampf oder Bögen sind am Anfang besser.
- **Crafting lernen:** `e` zum Essen, `c` zum Crafting-Menü. Zuerst Wasser abkochen und einfache Waffen bauen.
- **NPCs:** Misstrauisch, aber nicht immer feindlich. Können Quests geben und handeln.
- **Evolution:** Zombies verändern sich nach Wochen — die Ruhe am Anfang nutzen, um Skills aufzubauen.

## Empfohlene Mods

| Mod | Effekt | Empfehlung |
|---|---|---|
| **Survivor Bias** | Bessere Charakter-Optionen beim Setup | Empfohlen — hilft beim Build-Verständnis |
| **Disable NPC Needs** | NPCs brauchen keine Nahrung/Wasser | Optional — reduziert Micro-Management mit Begleitern |
| **More Locations** | Mehr POIs auf der Karte | Optional — mehr Erkundungsziele |

## Anpassungen

**Noch etwas leichter:**

```json
"ITEM_SPAWNRATE": 1.5,
"SPAWN_DENSITY": 0.8,
"EVOLUTION_INVERSE_MULTIPLIER": 4.0
```

**Bereit für mehr Herausforderung (Übergang zu Hardcore):**

```json
"ITEM_SPAWNRATE": 0.8,
"SPAWN_DENSITY": 1.3,
"EVOLUTION_INVERSE_MULTIPLIER": 1.0
```
