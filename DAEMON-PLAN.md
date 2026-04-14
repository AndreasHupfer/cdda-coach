# Plan: CDDA Live Coach Daemon

## Context
Der User möchte einen Python-Daemon, der den CDDA-Save-Ordner beobachtet und bei jedem Speichern automatisch ein Coach-Briefing generiert — ohne Benutzerinteraktion. Die bestehende Coach-Persona aus `.claude/skills/cdda-coach.md` wird als System-Prompt für direkte Anthropic-API-Calls wiederverwendet. Das Ergebnis wird im Terminal angezeigt und als Obsidian-Note gespeichert.

---

## Zu erstellende Dateien

| Datei | Beschreibung |
|---|---|
| `/home/andreas/cdda-coach/cdda-daemon.py` | Haupt-Daemon (~280 Zeilen) |
| `/home/andreas/cdda-coach/requirements.txt` | Python-Abhängigkeiten |

**Zu lesende Quelldatei** (als System-Prompt-Basis):
- `/home/andreas/cdda-coach/.claude/skills/cdda-coach.md`

---

## Abhängigkeiten

```bash
sudo apt install inotify-tools     # inotifywait (nicht installiert)
pip install anthropic colorama     # Python-Pakete (nicht installiert)
export ANTHROPIC_API_KEY=sk-...    # Pflicht-Umgebungsvariable
```

`requirements.txt`:
```
anthropic>=0.40.0
colorama>=0.4.6
```

---

## Daemon-Architektur (Flat Module, ~280 Zeilen)

```
cdda-daemon.py
├── CONFIG-Konstanten
├── load_coach_skill(path) -> str            # cdda-coach.md laden, Frontmatter strippen
├── extract_char_data(sav_path, char_name) -> dict | None  # .sav JSON → kompakter Snapshot
├── load_previous_sessions(obsidian_dir, char_name) -> str  # Letzte 3 Notes für Kontext
├── build_user_prompt(char_data, prev_sessions) -> str  # Dict + History → User-Message
├── ask_save_to_obsidian() -> bool           # Interaktive [j/N]-Rückfrage
├── call_api(char_data, prev_sessions) -> str  # Anthropic API (claude-sonnet-4-6)
├── print_briefing(text, char_name, ts)      # ANSI-Farben via colorama
├── write_obsidian_note(obsidian_dir, char_name, text) # Obsidian-Note schreiben/anhängen
├── find_sav_file(save_dir) -> Path | None   # Neueste .sav im Save-Baum finden
├── on_save_detected(save_dir, obsidian_dir) # Pipeline: lesen → API → print → note
├── watch_loop(save_dir, obsidian_dir)       # inotifywait subprocess + Debounce
└── main() / argparse
```

---

## Stack-Entscheidung

**Einfaches Python-Script** (`cdda-daemon.py`, ~300 Zeilen). Begründung:
- Keine unnötige Komplexität für den aktuellen Scope
- Der Daemon läuft immer für eine Save-Directory (eine CDDA-Instanz zur Zeit)
- Mehrere Charaktere werden **sequentiell** gespielt — der Daemon erkennt automatisch welcher Charakter gerade aktiv ist (neueste `.sav`)
- Obsidian-Notes pro Charakter (`YYYY-MM-DD-<charname>.md`) bauen über Sessions hinweg eine vollständige Geschichte auf → Coach-Kontext wächst mit jeder Session
- Strukturiertes Frontmatter (character, date, tags) ermöglicht spätere Statistik-Auswertung via Obsidian Bases oder separates Analyse-Script
- Wenn ein Web-Dashboard oder SQLite später kommt, können die Funktionen ohne Refactor extrahiert werden

---

## Geänderte Anforderungen (Feedback-Runde)

1. **Obsidian-Speichern nach Rückfrage**: Terminal-Ausgabe ist automatisch. Danach fragt der Daemon `Briefing in Obsidian speichern? [j/N]:`. Nur bei `j`/`y` wird die Note geschrieben.
2. **Session-Gedächtnis via Obsidian**: Vor dem API-Call liest der Daemon vorherige Session-Notes des Charakters aus `~/obsidian-MSB/CDDA/Sessions/` und übergibt sie dem Coach als Kontext. So kann der Coach auf frühere Sessions Bezug nehmen.
3. **Skill-/Chat-Kompatibilität**: Der Daemon ist ein eigenständiges Python-Skript. `/cdda-coach` im Claude Code Chat und alle anderen Skills funktionieren weiterhin unverändert — kein Konflikt.

---

## Schlüssel-Implementierungen

### 1. File Watching (inotifywait)

```python
cmd = ["inotifywait", "-m", "-r", "-e", "close_write",
       "--format", "%w%f", str(save_dir)]
proc = subprocess.Popen(cmd, stdout=PIPE, stderr=DEVNULL, text=True)

for line in proc.stdout:
    path = line.strip()
    if path.endswith(".sav") or path.endswith("world_timestamp.json"):
        # Debounce: Timer canceln und neu starten
        if _debounce_timer: _debounce_timer.cancel()
        _debounce_timer = threading.Timer(2.0, on_save_detected, args=[...])
        _debounce_timer.start()
```

### 2. Character-Daten extrahieren (`.sav` JSON → ~600 Zeichen)

Extrahierte Felder (keine Arrays senden, nur Counts/summaries):
- `stats`: `str_cur`, `dex_cur`, `int_cur`, `per_cur`
- `hp`: `hp_cur[0-5]` / `hp_max[0-5]` → Body-Part-Dict (`torso`, `head`, …)
- `needs`: `hunger`, `thirst`, `fatigue`, `pain`, `stim`
- `morale`: Summe aller `morale[].val`
- `skills`: Top-10 nach Level (nur > 0), ohne rust=0 Rausch
- `effects`: Liste der Keys (max. 8)
- `bionics`: Liste der IDs (max. 10)
- `mutations`: Liste der Keys/IDs (max. 8)
- `worn_count`, `inv_count`: Nur Anzahl, keine Items
- `game_date`: Berechnet aus `turn` → `Jahr X, Jahreszeit Tag Y`

Validierung: Wenn `str_cur` fehlt → `None` (kein Charakter-Save → überspringen).

### 3. Session-Gedächtnis: Vorherige Notes lesen

```python
def load_previous_sessions(obsidian_dir: Path, char_name: str, max_notes: int = 3) -> str:
    """
    Liest die letzten max_notes Session-Notes für diesen Charakter aus
    ~/obsidian-MSB/CDDA/Sessions/ und gibt sie als Text zurück.
    Gibt leeren String zurück wenn keine Notes existieren.
    """
    sessions_dir = obsidian_dir / "CDDA" / "Sessions"
    safe_name = sanitize_filename(char_name)
    pattern = f"*-{safe_name}.md"
    notes = sorted(sessions_dir.glob(pattern))[-max_notes:]
    if not notes:
        return ""
    texts = []
    for note_path in notes:
        texts.append(f"### {note_path.stem}\n{note_path.read_text(encoding='utf-8')[:2000]}")
    return "\n\n".join(texts)
```

Die gelesenen Sessions werden als zusätzlicher Abschnitt in den User-Prompt eingefügt:

```python
def build_user_prompt(char_data: dict, previous_sessions: str) -> str:
    char_json = json.dumps(char_data, indent=2, ensure_ascii=False)
    parts = [f"**Aktueller Spielstand:**\n```json\n{char_json}\n```"]
    if previous_sessions:
        parts.append(f"**Vorherige Sessions (zur Erinnerung):**\n{previous_sessions}")
    parts.append("Erstelle das Coach-Briefing.")
    return "\n\n".join(parts)
```

### 4. System-Prompt (mit Prompt Caching)

```python
skill_text = load_coach_skill(SKILL_FILE)  # Frontmatter + $ARGUMENTS entfernt
BRIEFING_FORMAT = """
## Briefing-Format
Du erhältst einen Charakter-Snapshot als JSON. Antworte mit genau diesen 4 Abschnitten:

## Status
Überblick: Name, Spieltag, HP (nach Körperteil), Bedürfnisse, Morale.

## Warnungen
⚠️ Kritische Punkte — max. 4 Punkte.

## Chancen
✅ Sofort umsetzbare Schritte — max. 4 Punkte.

## Analyse
2-3 Sätze strategische Einschätzung. Konkret, handlungsorientiert.

Regeln: Anti-Cheat (nur was der Char weiß), max. 400 Wörter, Deutsch.
"""
SYSTEM_PROMPT = skill_text + "\n\n---\n\n" + BRIEFING_FORMAT
```

API-Call mit Prompt Cache auf system:
```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=[{"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}],
    messages=[{"role": "user", "content": build_user_prompt(char_data)}],
)
```

### 4. Terminal-Ausgabe (colorama)

```
=== SAVE DETECTED 14:32:07 — Brigitte ===   ← CYAN
## Status                                    ← YELLOW
HP: torso 60/80 ...                          ← weiß
## Warnungen                                 ← YELLOW
⚠️ Hunger kritisch                           ← ROT
## Chancen                                   ← YELLOW
✅ Nahkampf-Skill hoch                       ← GRÜN
```

Erkennungsregeln:
- `⚠`, `warnung`, `kritisch`, `gefahr`, `sofort` → Rot
- `✅`, `chance`, `gut `, `sicher` → Grün
- Zeile beginnt mit `##` → Gelb

### 5. Rückfrage vor Obsidian-Speichern

Nach der Terminal-Ausgabe:
```python
def ask_save_to_obsidian() -> bool:
    """Fragt den User interaktiv ob das Briefing gespeichert werden soll."""
    try:
        answer = input(f"\n{Fore.CYAN}Briefing in Obsidian speichern? [j/N]: {Style.RESET_ALL}").strip().lower()
        return answer in ("j", "y", "ja", "yes")
    except (EOFError, KeyboardInterrupt):
        return False
```

Flow in `on_save_detected()`:
```python
briefing = call_api(char_data, previous_sessions)
print_briefing(briefing, char_name, timestamp)
if ask_save_to_obsidian():
    write_obsidian_note(obsidian_dir, char_name, briefing)
```

### 6. Obsidian-Note (`~/obsidian-MSB/CDDA/Sessions/`)

**Neue Note** (`YYYY-MM-DD-<charname>.md`):
```markdown
---
title: "CDDA Session – Brigitte"
character: Brigitte
tags: [cdda, gaming, session, coach-briefing]
created: 2026-04-14
updated: 2026-04-14
---

# CDDA Session – Brigitte

## 14:32:07 — Autosave

<briefing>
```

**Gleicher Tag, zweiter Save (User hat `j` bestätigt)** → anhängen:
```markdown

---

## 16:17:43 — Autosave

<briefing>
```
Beim Anhängen: `updated:` im Frontmatter per `re.sub` aktualisieren.

---

## Fehlerbehandlung

| Szenario | Verhalten |
|---|---|
| `save_dir` existiert nicht | Rot-Fehlermeldung + `sys.exit(1)` |
| `inotifywait` nicht installiert | `FileNotFoundError` → Installationshinweis + exit |
| Kein `.sav` (kein aktiver Charakter) | Gelb "Kein aktiver Charakter" → continue |
| `ANTHROPIC_API_KEY` fehlt | Prüfung bei Start → Fehlermeldung + exit |
| API-Fehler | Rot-Fehlermeldung → Daemon läuft weiter |
| Obsidian-Dir nicht schreibbar | `OSError` logged → Terminal-Ausgabe trotzdem |
| SIGINT/SIGTERM | Debounce-Timer canceln, subprocess terminieren, sauber exit |

---

## CLI

```bash
python3 cdda-daemon.py
python3 cdda-daemon.py --save-dir ~/opt/dda/game0/save --obsidian-dir ~/obsidian-MSB
```

Argumente: `--save-dir` (default: `~/opt/dda/game0/save`), `--obsidian-dir` (default: `~/obsidian-MSB`)

---

## Implementierungsreihenfolge

1. Plan als `DAEMON-PLAN.md` ins Projektverzeichnis `/home/andreas/cdda-coach/` kopieren
2. `requirements.txt` erstellen
3. `cdda-daemon.py` implementieren
4. Abhängigkeiten installieren + manuell testen

---

## Verifikation

1. `sudo apt install inotify-tools && pip install anthropic colorama`
2. `export ANTHROPIC_API_KEY=sk-...`
3. Daemon starten: `python3 cdda-daemon.py`
4. Test ohne CDDA: `touch ~/opt/dda/game0/save/Cowles/test.sav` → "Kein aktiver Charakter"
5. Mit CDDA laufend: CDDA starten, speichern → Briefing erscheint im Terminal, dann Rückfrage `[j/N]`
6. Bei `j`: Note in `~/obsidian-MSB/CDDA/Sessions/` prüfen. Bei `n`: kein File-Write.
7. Zweiter Save selber Tag, `j` bestätigt → Note wird angehängt, nicht neu erstellt
8. Zweite Session mit gleichem Charakter: Coach referenziert vorherige Session-Inhalte im Briefing
9. Ctrl+C → sauberes Beenden bestätigen
10. Im Claude Code Chat parallel `/cdda-coach` aufrufen → funktioniert unabhängig vom Daemon
