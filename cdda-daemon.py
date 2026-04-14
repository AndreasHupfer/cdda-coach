#!/usr/bin/env python3
"""
cdda-daemon.py — CDDA Live Coach Daemon

Beobachtet das CDDA-Save-Verzeichnis mit inotifywait und generiert bei jedem
Speichern automatisch ein Coach-Briefing via Anthropic API.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from subprocess import PIPE, DEVNULL

try:
    import anthropic
except ImportError:
    print("anthropic nicht installiert. Bitte: pip install anthropic colorama pyzstd")
    sys.exit(1)

try:
    import pyzstd
except ImportError:
    print("pyzstd nicht installiert. Bitte: pip install pyzstd")
    sys.exit(1)

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
except ImportError:
    print("colorama nicht installiert. Bitte: pip install anthropic colorama")
    sys.exit(1)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
SKILL_FILE = SCRIPT_DIR / ".claude" / "skills" / "cdda-coach.md"
DEFAULT_OBSIDIAN_DIR = Path.home() / "obsidian-MSB"


def load_env_file() -> dict[str, str]:
    """Liest Schlüssel-Wert-Paare aus .env im Projektverzeichnis."""
    env_file = SCRIPT_DIR / ".env"
    result: dict[str, str] = {}
    if not env_file.exists():
        return result
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


_ENV = load_env_file()

# Werte aus .env in os.environ übernehmen (nur wenn noch nicht gesetzt)
for _k, _v in _ENV.items():
    os.environ.setdefault(_k, _v)


def _default_save_dir() -> Path:
    cdda_root = _ENV.get("CDDA_ROOT")
    if cdda_root:
        return Path(cdda_root) / "save"
    return Path.home() / "opt" / "dda" / "game0" / "save"


DEFAULT_SAVE_DIR = _default_save_dir()
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
DEBOUNCE_SECONDS = 2.0
DEFAULT_SEASON_LENGTH = 91  # Tage pro Jahreszeit (CDDA-Standard)

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
BP_NAMES = ["torso", "head", "l_arm", "r_arm", "l_leg", "r_leg"]
SEASON_NAMES = ["Frühling", "Sommer", "Herbst", "Winter"]

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

# ---------------------------------------------------------------------------
# GLOBAL STATE
# ---------------------------------------------------------------------------
_debounce_timer: threading.Timer | None = None
_inotify_proc: subprocess.Popen | None = None  # type: ignore[type-arg]
_client: anthropic.Anthropic | None = None
_system_prompt: str | None = None


# ---------------------------------------------------------------------------
# SKILL LADEN
# ---------------------------------------------------------------------------
def load_coach_skill(path: Path) -> str:
    """Lädt cdda-coach.md, entfernt YAML-Frontmatter und $ARGUMENTS."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"{Fore.RED}Skill-Datei nicht gefunden: {path}{Style.RESET_ALL}")
        return ""

    # YAML-Frontmatter entfernen (--- ... ---)
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:].lstrip()

    # $ARGUMENTS-Platzhalter entfernen
    return text.replace("$ARGUMENTS", "").strip()


def get_system_prompt() -> str:
    """Gibt den (gecachten) System-Prompt zurück."""
    global _system_prompt
    if _system_prompt is None:
        skill_text = load_coach_skill(SKILL_FILE)
        _system_prompt = skill_text + "\n\n---\n\n" + BRIEFING_FORMAT
    return _system_prompt


# ---------------------------------------------------------------------------
# SPIELSTAND EXTRAHIEREN
# ---------------------------------------------------------------------------
def calculate_game_date(turn: int, season_length: int = DEFAULT_SEASON_LENGTH) -> str:
    """Berechnet das Spieldatum aus dem Turn-Zähler."""
    total_minutes = turn // 60
    total_hours = total_minutes // 60
    total_days = total_hours // 24

    current_hour = total_hours % 24
    current_minute = total_minutes % 60

    days_per_year = season_length * 4
    year = total_days // days_per_year + 1
    day_in_year = total_days % days_per_year
    season_idx = day_in_year // season_length
    day_in_season = day_in_year % season_length + 1
    season = SEASON_NAMES[season_idx % 4]

    return f"Jahr {year}, {season} Tag {day_in_season}, {current_hour:02d}:{current_minute:02d}"


def decompress_zzip(path: Path) -> bytes:
    """Dekomprimiert eine CDDA .sav.zzip-Datei (zstd-Payload nach Custom-Header)."""
    data = path.read_bytes()
    offset = data.find(ZSTD_MAGIC)
    if offset == -1:
        raise ValueError(f"Kein zstd-Frame in {path} gefunden")
    dctx = pyzstd.ZstdDecompressor()
    return dctx.decompress(data[offset:], max_length=50 * 1024 * 1024)


def extract_char_data(sav_path: Path) -> dict | None:
    """Parst die .sav.zzip-Datei und extrahiert einen kompakten Charakter-Snapshot."""
    try:
        if sav_path.suffix == ".zzip":
            raw_bytes = decompress_zzip(sav_path)
            raw: dict = json.loads(raw_bytes)
        else:
            raw = json.loads(sav_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError) as e:
        print(f"{Fore.YELLOW}Konnte {sav_path.name} nicht lesen: {e}{Style.RESET_ALL}")
        return None

    # Validierung: Game-Save mit player-Block erkennen
    p = raw.get("player")
    if not isinstance(p, dict):
        return None

    # Stats
    stats = {
        "str": p.get("str_cur"),
        "dex": p.get("dex_cur"),
        "int": p.get("int_cur"),
        "per": p.get("per_cur"),
    }

    # HP nach Körperteil (neues Format: body-Dict, enthält nur vorhandene Parts)
    body = p.get("body", {})
    hp: dict[str, str] = {}
    for bp, part in body.items():
        if isinstance(part, dict) and "hp_cur" in part:
            hp[bp] = f"{part['hp_cur']}/{part.get('hp_max', '?')}"

    # Bedürfnisse
    needs = {k: p.get(k) for k in ("hunger", "thirst", "sleepiness", "pain", "stamina")}

    # Morale (Summe)
    morale_list = p.get("morale", [])
    morale_total = sum(m.get("val", 0) for m in morale_list if isinstance(m, dict))

    # Skills: Top-10 nach Level (nur > 0)
    raw_skills = p.get("skills", {})
    skill_dict: dict[str, int] = {}
    if isinstance(raw_skills, dict):
        for skill_name, data in raw_skills.items():
            lvl = data.get("level", 0) if isinstance(data, dict) else int(data or 0)
            if lvl > 0:
                skill_dict[skill_name] = lvl
    top_skills = dict(sorted(skill_dict.items(), key=lambda x: x[1], reverse=True)[:10])

    # Effects (max. 8) — neues Format: Dict von Dicts
    raw_effects = p.get("effects", {})
    if isinstance(raw_effects, dict):
        effects = list(raw_effects.keys())[:8]
    elif isinstance(raw_effects, list):
        effects = [
            e.get("type", str(e)) if isinstance(e, dict) else str(e)
            for e in raw_effects[:8]
        ]
    else:
        effects = []

    # Bioniken (max. 10)
    raw_bionics = p.get("bionics", [])
    if isinstance(raw_bionics, list):
        bionics = [
            b.get("id", str(b)) if isinstance(b, dict) else str(b)
            for b in raw_bionics[:10]
        ]
    else:
        bionics = []

    # Mutationen (max. 8)
    raw_mutations = p.get("mutations", {})
    if isinstance(raw_mutations, dict):
        mutations = list(raw_mutations.keys())[:8]
    elif isinstance(raw_mutations, list):
        mutations = [
            m.get("id", str(m)) if isinstance(m, dict) else str(m)
            for m in raw_mutations[:8]
        ]
    else:
        mutations = []

    # Inventar-Anzahl
    worn_count = len(p.get("worn", []))
    inv_count = len(p.get("inv", []))

    # Charakter-Name und Spieldatum
    char_name: str = p.get("name", sav_path.stem)
    turn = raw.get("turn", 0)
    game_date = calculate_game_date(turn)

    return {
        "name": char_name,
        "game_date": game_date,
        "stats": stats,
        "hp": hp,
        "needs": needs,
        "morale": morale_total,
        "skills": top_skills,
        "effects": effects,
        "bionics": bionics,
        "mutations": mutations,
        "worn_count": worn_count,
        "inv_count": inv_count,
    }


# ---------------------------------------------------------------------------
# OBSIDIAN SESSION-GEDÄCHTNIS
# ---------------------------------------------------------------------------
def sanitize_filename(name: str) -> str:
    """Entfernt dateiunsichere Zeichen."""
    return re.sub(r"[^\w\-]", "_", name)


def load_previous_sessions(obsidian_dir: Path, char_name: str, max_notes: int = 3) -> str:
    """Liest die letzten max_notes Session-Notes für diesen Charakter."""
    sessions_dir = obsidian_dir / "CDDA" / "Sessions"
    if not sessions_dir.exists():
        return ""
    safe_name = sanitize_filename(char_name)
    pattern = f"*-{safe_name}.md"
    notes = sorted(sessions_dir.glob(pattern))[-max_notes:]
    if not notes:
        return ""
    texts = []
    for note_path in notes:
        content = note_path.read_text(encoding="utf-8")[:2000]
        texts.append(f"### {note_path.stem}\n{content}")
    return "\n\n".join(texts)


# ---------------------------------------------------------------------------
# PROMPT BAUEN
# ---------------------------------------------------------------------------
def build_user_prompt(char_data: dict, previous_sessions: str) -> str:
    """Erstellt die User-Message für den API-Call."""
    char_json = json.dumps(char_data, indent=2, ensure_ascii=False)
    parts = [f"**Aktueller Spielstand:**\n```json\n{char_json}\n```"]
    if previous_sessions:
        parts.append(f"**Vorherige Sessions (zur Erinnerung):**\n{previous_sessions}")
    parts.append("Erstelle das Coach-Briefing.")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# API-CALL
# ---------------------------------------------------------------------------
def call_api(char_data: dict, previous_sessions: str) -> str:
    """Ruft die Anthropic API mit Prompt Caching auf dem System-Prompt auf."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()

    system_prompt = get_system_prompt()
    user_prompt = build_user_prompt(char_data, previous_sessions)

    response = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TERMINAL-AUSGABE
# ---------------------------------------------------------------------------
def colorize_line(line: str) -> str:
    """Färbt eine Zeile basierend auf ihrem Inhalt ein."""
    lower = line.lower()
    if line.startswith("##"):
        return f"{Fore.YELLOW}{line}{Style.RESET_ALL}"
    if any(k in lower for k in ("⚠", "warnung", "kritisch", "gefahr", "sofort")):
        return f"{Fore.RED}{line}{Style.RESET_ALL}"
    if any(k in lower for k in ("✅", "chance", "gut ", "sicher")):
        return f"{Fore.GREEN}{line}{Style.RESET_ALL}"
    return line


def print_briefing(text: str, char_name: str, ts: str) -> None:
    """Gibt das Briefing mit ANSI-Farben aus."""
    sep = "=" * 50
    print(f"\n{Fore.CYAN}{sep}")
    print(f"=== SAVE DETECTED {ts} — {char_name} ===")
    print(f"{sep}{Style.RESET_ALL}\n")
    for line in text.splitlines():
        print(colorize_line(line))
    print()


# ---------------------------------------------------------------------------
# OBSIDIAN NOTE
# ---------------------------------------------------------------------------
def ask_save_to_obsidian() -> bool:
    """Fragt interaktiv, ob das Briefing gespeichert werden soll."""
    try:
        answer = input(
            f"{Fore.CYAN}Briefing in Obsidian speichern? [j/N]: {Style.RESET_ALL}"
        ).strip().lower()
        return answer in ("j", "y", "ja", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def write_obsidian_note(obsidian_dir: Path, char_name: str, briefing: str) -> None:
    """Schreibt oder ergänzt eine Session-Note in Obsidian."""
    sessions_dir = obsidian_dir / "CDDA" / "Sessions"
    try:
        sessions_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"{Fore.RED}Obsidian-Verzeichnis nicht beschreibbar: {e}{Style.RESET_ALL}")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H:%M:%S")
    safe_name = sanitize_filename(char_name)
    note_path = sessions_dir / f"{today}-{safe_name}.md"

    try:
        if note_path.exists():
            # An bestehende Note anhängen, updated:-Datum aktualisieren
            content = note_path.read_text(encoding="utf-8")
            content = re.sub(
                r"^(updated:\s*).*$",
                f"\\g<1>{today}",
                content,
                flags=re.MULTILINE,
            )
            content += f"\n---\n\n## {ts} — Autosave\n\n{briefing}\n"
            note_path.write_text(content, encoding="utf-8")
        else:
            # Neue Note erstellen
            frontmatter = (
                f"---\n"
                f'title: "CDDA Session – {char_name}"\n'
                f"character: {char_name}\n"
                f"tags: [cdda, gaming, session, coach-briefing]\n"
                f"created: {today}\n"
                f"updated: {today}\n"
                f"---\n\n"
                f"# CDDA Session – {char_name}\n\n"
                f"## {ts} — Autosave\n\n"
                f"{briefing}\n"
            )
            note_path.write_text(frontmatter, encoding="utf-8")
        print(f"{Fore.GREEN}Note gespeichert: {note_path}{Style.RESET_ALL}")
    except OSError as e:
        print(f"{Fore.RED}Fehler beim Schreiben der Note: {e}{Style.RESET_ALL}")


# ---------------------------------------------------------------------------
# SAVE-DATEI FINDEN
# ---------------------------------------------------------------------------
def find_sav_file(save_dir: Path) -> tuple[Path, str] | None:
    """Findet die zuletzt modifizierte .sav.zzip-Datei im Save-Baum."""
    sav_files = list(save_dir.rglob("*.sav.zzip"))
    if not sav_files:
        # Fallback: unkomprimierte .sav (ältere CDDA-Versionen)
        sav_files = [f for f in save_dir.rglob("*.sav") if not f.name.endswith(".backup")]
    if not sav_files:
        return None
    newest = max(sav_files, key=lambda f: f.stat().st_mtime)
    # Charakter-Name aus base64-kodiertem Dateinamen dekodieren
    import base64
    stem = newest.name.replace(".sav.zzip", "").replace(".sav", "")
    try:
        char_name = base64.b64decode(stem.lstrip("#") + "==").decode("utf-8")
    except Exception:
        char_name = stem
    return newest, char_name


# ---------------------------------------------------------------------------
# PIPELINE
# ---------------------------------------------------------------------------
def on_save_detected(save_dir: Path, obsidian_dir: Path) -> None:
    """Haupt-Pipeline: lesen → API → drucken → Rückfrage → Note."""
    result = find_sav_file(save_dir)
    if result is None:
        print(f"{Fore.YELLOW}Kein aktiver Charakter gefunden — überspringe.{Style.RESET_ALL}")
        return

    sav_path, char_name = result
    char_data = extract_char_data(sav_path)
    if char_data is None:
        print(
            f"{Fore.YELLOW}Kein aktiver Charakter in {sav_path.name} — überspringe.{Style.RESET_ALL}"
        )
        return

    previous_sessions = load_previous_sessions(obsidian_dir, char_name)

    print(f"{Fore.CYAN}API-Call für {char_name}...{Style.RESET_ALL}")
    try:
        briefing = call_api(char_data, previous_sessions)
    except anthropic.APIError as e:
        print(f"{Fore.RED}API-Fehler: {e}{Style.RESET_ALL}")
        return
    except Exception as e:
        print(f"{Fore.RED}Unerwarteter Fehler beim API-Call: {e}{Style.RESET_ALL}")
        return

    ts = datetime.now().strftime("%H:%M:%S")
    print_briefing(briefing, char_name, ts)

    if ask_save_to_obsidian():
        write_obsidian_note(obsidian_dir, char_name, briefing)


# ---------------------------------------------------------------------------
# WATCH-LOOP
# ---------------------------------------------------------------------------
def watch_loop(save_dir: Path, obsidian_dir: Path) -> None:
    """Beobachtet save_dir mit inotifywait und löst bei .sav-Writes aus."""
    global _debounce_timer, _inotify_proc

    cmd = [
        "inotifywait", "-m", "-r",
        "-e", "close_write",
        "--format", "%w%f",
        str(save_dir),
    ]

    try:
        _inotify_proc = subprocess.Popen(cmd, stdout=PIPE, stderr=DEVNULL, text=True)
    except FileNotFoundError:
        print(f"{Fore.RED}inotifywait nicht gefunden.{Style.RESET_ALL}")
        print("Bitte installieren: sudo apt install inotify-tools")
        sys.exit(1)

    print(f"{Fore.GREEN}Daemon läuft. Beobachte: {save_dir}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Drücke Ctrl+C zum Beenden.{Style.RESET_ALL}\n")

    for line in _inotify_proc.stdout:  # type: ignore[union-attr]
        path = line.strip()
        if path.endswith(".sav.zzip") or path.endswith(".sav") or path.endswith("world_timestamp.json"):
            if _debounce_timer is not None:
                _debounce_timer.cancel()
            _debounce_timer = threading.Timer(
                DEBOUNCE_SECONDS,
                on_save_detected,
                args=[save_dir, obsidian_dir],
            )
            _debounce_timer.daemon = True
            _debounce_timer.start()


# ---------------------------------------------------------------------------
# SHUTDOWN
# ---------------------------------------------------------------------------
def shutdown(*_: object) -> None:
    """Sauberes Beenden: Debounce-Timer canceln, inotifywait terminieren."""
    global _debounce_timer, _inotify_proc
    print(f"\n{Fore.CYAN}Daemon wird beendet...{Style.RESET_ALL}")
    if _debounce_timer is not None:
        _debounce_timer.cancel()
    if _inotify_proc is not None:
        _inotify_proc.terminate()
    sys.exit(0)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="CDDA Live Coach Daemon — generiert bei jedem Speichern ein Briefing."
    )
    parser.add_argument(
        "--save-dir",
        type=Path,
        default=DEFAULT_SAVE_DIR,
        help=f"CDDA Save-Verzeichnis (default: {DEFAULT_SAVE_DIR})",
    )
    parser.add_argument(
        "--obsidian-dir",
        type=Path,
        default=DEFAULT_OBSIDIAN_DIR,
        help=f"Obsidian-Vault-Verzeichnis (default: {DEFAULT_OBSIDIAN_DIR})",
    )
    args = parser.parse_args()

    save_dir = args.save_dir.expanduser()
    obsidian_dir = args.obsidian_dir.expanduser()

    # Validierung
    if not save_dir.exists():
        print(f"{Fore.RED}Save-Verzeichnis nicht gefunden: {save_dir}{Style.RESET_ALL}")
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"{Fore.RED}ANTHROPIC_API_KEY ist nicht gesetzt.{Style.RESET_ALL}")
        print("Bitte: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # Signal-Handler
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"{Fore.CYAN}CDDA Live Coach Daemon{Style.RESET_ALL}")
    print(f"Save-Dir:    {save_dir}")
    print(f"Obsidian:    {obsidian_dir}")
    print(f"Modell:      {MODEL}")
    print()

    watch_loop(save_dir, obsidian_dir)


if __name__ == "__main__":
    main()
