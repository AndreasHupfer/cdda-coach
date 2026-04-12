#!/usr/bin/env python3
"""CDDA Save Reader — liest Spielinformationen aus CDDA-Savefiles und gibt JSON aus."""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

try:
    import pyzstd
except ImportError:
    print("Fehler: pyzstd nicht installiert. Bitte: pip install pyzstd", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def load_env(project_root: Path) -> dict:
    """Liest KEY=VALUE-Paare aus .env im Projektroot."""
    env_path = project_root / ".env"
    result = {}
    if not env_path.exists():
        return result
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def decompress_zzip(path: Path) -> bytes:
    """Dekomprimiert eine CDDA .zzip-Datei (Custom-Container + zstd-Payload).

    CDDA wraps the zstd frame with several zstd Skippable Frames containing
    metadata. We scan for the real zstd magic and decompress from there.
    """
    data = path.read_bytes()
    offset = data.find(ZSTD_MAGIC)
    if offset == -1:
        raise ValueError(f"Kein zstd-Frame in {path} gefunden")
    dctx = pyzstd.ZstdDecompressor()
    return dctx.decompress(data[offset:], max_length=50 * 1024 * 1024)


def decode_char_name(encoded: str) -> str:
    """Dekodiert den base64-kodierten Charakternamen aus dem Dateinamen."""
    # Dateiname-Präfix ist '#' + base64, ohne '#'
    b64 = encoded.lstrip("#")
    try:
        return base64.b64decode(b64 + "==").decode("utf-8")
    except Exception:
        return encoded


def find_world_dir(save_root: Path, world: str | None) -> Path:
    """Findet das Weltverzeichnis."""
    if world:
        candidate = save_root / world
        if not candidate.is_dir():
            # Case-insensitive fallback
            for d in save_root.iterdir():
                if d.is_dir() and d.name.lower() == world.lower():
                    return d
            raise FileNotFoundError(f"Welt '{world}' nicht in {save_root}")
        return candidate

    worlds = [d for d in save_root.iterdir() if d.is_dir()]
    if not worlds:
        raise FileNotFoundError(f"Keine Welten in {save_root}")
    if len(worlds) > 1:
        names = [w.name for w in worlds]
        raise ValueError(
            f"Mehrere Welten gefunden: {names}. Bitte --world angeben."
        )
    return worlds[0]


def find_char_prefix(world_dir: Path, char_name: str | None) -> tuple[str, str]:
    """Gibt (prefix, decoded_name) des Charakters zurück.

    prefix ist der Dateiname-Präfix (z.B. '#TWF4IEhlbGZlbmJlcmdlcg==').
    """
    candidates = list(world_dir.glob("*.sav.zzip"))
    if not candidates:
        raise FileNotFoundError(f"Kein Savegame in {world_dir}")

    chars = {}
    for f in candidates:
        prefix = f.name.replace(".sav.zzip", "")
        name = decode_char_name(prefix)
        chars[name] = prefix

    if char_name:
        if char_name not in chars:
            raise ValueError(f"Charakter '{char_name}' nicht gefunden. Verfügbar: {list(chars)}")
        return chars[char_name], char_name

    if len(chars) > 1:
        raise ValueError(
            f"Mehrere Charaktere gefunden: {list(chars)}. Bitte --char angeben."
        )
    name, prefix = next(iter(chars.items()))
    return prefix, name


def load_save_json(world_dir: Path, prefix: str) -> dict:
    """Lädt und parst die .sav.zzip-Datei des Charakters."""
    sav_path = world_dir / f"{prefix}.sav.zzip"
    raw = decompress_zzip(sav_path)
    return json.loads(raw)


def load_json_file(path: Path) -> dict | list:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Item-Extraktion
# ---------------------------------------------------------------------------

def extract_items_from_pocket(pocket: dict) -> list[dict]:
    """Extrahiert Items (flach) aus einem Pocket-Eintrag."""
    items = []
    for item in pocket.get("contents", []):
        entry = {"typeid": item.get("typeid", "?")}
        if "charges" in item:
            entry["charges"] = item["charges"]
        tags = item.get("item_tags", [])
        if tags:
            entry["tags"] = tags
        # Rekursiv Tascheninhalte sammeln
        nested = []
        for content_pocket in (item.get("contents", {}).get("contents") or []):
            nested.extend(extract_items_from_pocket(content_pocket))
        if nested:
            entry["contents"] = nested
        items.append(entry)
    return items


def extract_worn_summary(worn_list: list) -> list[dict]:
    """Erstellt eine kompakte Zusammenfassung der getragenen Items."""
    result = []
    for item in worn_list:
        entry = {"typeid": item.get("typeid", "?")}
        tags = item.get("item_tags", [])
        if tags:
            entry["tags"] = tags
        # Tascheninhalte
        pocket_contents = []
        for pocket in (item.get("contents", {}).get("contents") or []):
            pocket_contents.extend(extract_items_from_pocket(pocket))
        if pocket_contents:
            entry["pocket_contents"] = pocket_contents
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_status(save: dict) -> dict:
    p = save.get("player", {})
    body = p.get("body", {})
    hp = {part: {"cur": v["hp_cur"], "max": v["hp_max"]} for part, v in body.items()}

    effects = {}
    for eff_name, eff_data in p.get("effects", {}).items():
        for bp, bp_data in eff_data.items():
            effects[eff_name] = {
                "duration": bp_data.get("duration"),
                "intensity": bp_data.get("intensity"),
            }

    morale = p.get("morale", [])
    morale_total = sum(m.get("val", 0) for m in morale) if morale else 0

    return {
        "name": p.get("name"),
        "turn": save.get("turn"),
        "location": p.get("location"),
        "pain": p.get("pain", 0),
        "hunger": p.get("hunger", 0),
        "thirst": p.get("thirst", 0),
        "sleepiness": p.get("sleepiness", 0),
        "sleep_deprivation": p.get("sleep_deprivation", 0),
        "stamina": p.get("stamina", 0),
        "speed": p.get("speed", 100) + p.get("speed_bonus", 0),
        "radiation": p.get("radiation", 0),
        "morale_total": morale_total,
        "morale_entries": morale,
        "effects": effects,
        "hp": hp,
    }


def cmd_inventory(save: dict) -> dict:
    p = save.get("player", {})
    inv_raw = p.get("inv", [])

    inv_items = []
    for item in inv_raw:
        entry = {"typeid": item.get("typeid", "?")}
        if "charges" in item:
            entry["charges"] = item["charges"]
        tags = item.get("item_tags", [])
        if tags:
            entry["tags"] = tags
        inv_items.append(entry)

    worn_raw = p.get("worn", {}).get("worn", [])
    worn_items = extract_worn_summary(worn_raw)

    return {
        "inventory": inv_items,
        "worn": worn_items,
    }


def cmd_skills(save: dict) -> dict:
    p = save.get("player", {})
    skills_raw = p.get("skills", {})
    active = {
        name: {
            "level": data["level"],
            "knowledge": data.get("knowledgeLevel", 0),
        }
        for name, data in skills_raw.items()
        if data.get("level", 0) > 0 or data.get("knowledgeLevel", 0) > 0
    }
    return {"skills": active}


def cmd_traits(save: dict) -> dict:
    p = save.get("player", {})
    # Filtere kosmetische Traits (Haarfarbe, Augenfarbe etc.)
    cosmetic_prefixes = ("eye_color", "hair_", "natural_hair_", "SKIN_")
    traits = [
        t for t in p.get("traits", [])
        if not any(t.startswith(prefix) for prefix in cosmetic_prefixes)
    ]
    return {"traits": traits}


def cmd_log(world_dir: Path, prefix: str) -> dict:
    log_path = world_dir / f"{prefix}.log"
    events = load_json_file(log_path)
    if isinstance(events, list):
        return {"log": events}
    return {"log": []}


def cmd_diary(world_dir: Path, prefix: str) -> dict:
    # Diary hat einen anderen base64-Namen (Name + "diary")
    diary_prefix = prefix.rstrip("=")
    # Suche nach _diary.json Pattern
    candidates = list(world_dir.glob("*diary*.json"))
    if not candidates:
        return {"diary": {"pages": []}}
    data = load_json_file(candidates[0])
    return {"diary": data}


def cmd_zones(world_dir: Path, prefix: str) -> dict:
    zones_path = world_dir / f"{prefix}.zones.json"
    data = load_json_file(zones_path)
    return {"zones": data if isinstance(data, list) else []}


def cmd_world(world_dir: Path) -> dict:
    opts = load_json_file(world_dir / "worldoptions.json")
    mods = load_json_file(world_dir / "mods.json")
    return {"worldoptions": opts, "mods": mods}


def cmd_raw(save: dict) -> dict:
    return {"player": save.get("player", {})}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

SUBCOMMANDS = {
    "status": "Vitalwerte, HP, Pain, Hunger, Thirst, Morale, Speed",
    "inventory": "Inventory-Items und getragene Ausrüstung",
    "skills": "Skills mit Level > 0",
    "traits": "Aktive Traits (ohne kosmetische)",
    "log": "Spiellog-Events",
    "diary": "Tagebucheinträge",
    "zones": "Zonen-Definitionen",
    "world": "Weltoptionen und aktive Mods",
    "raw": "Vollständiger player-JSON-Block",
}


def main():
    parser = argparse.ArgumentParser(
        description="CDDA Save Reader — gibt Spielinformationen als JSON aus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Subcommands:\n" + "\n".join(f"  {k:12} {v}" for k, v in SUBCOMMANDS.items()),
    )
    parser.add_argument(
        "subcommand",
        choices=list(SUBCOMMANDS),
        help="Welche Daten ausgegeben werden sollen",
    )
    parser.add_argument("--world", help="Weltname (auto-detect wenn nur eine Welt)")
    parser.add_argument("--char", help="Charaktername (auto-detect wenn nur ein Charakter)")
    parser.add_argument(
        "--indent", type=int, default=2, help="JSON-Einrückung (0 = kompakt)"
    )
    args = parser.parse_args()

    # Projektroot = zwei Ebenen über .claude/tools/
    project_root = Path(__file__).parent.parent.parent
    env = load_env(project_root)

    cdda_root = env.get("CDDA_ROOT") or os.environ.get("CDDA_ROOT")
    if not cdda_root:
        print("Fehler: CDDA_ROOT nicht in .env oder Umgebungsvariablen gesetzt.", file=sys.stderr)
        sys.exit(1)

    save_root = Path(cdda_root) / "save"
    if not save_root.exists():
        print(f"Fehler: Save-Verzeichnis nicht gefunden: {save_root}", file=sys.stderr)
        sys.exit(1)

    try:
        world_dir = find_world_dir(save_root, args.world)
        prefix, char_name = find_char_prefix(world_dir, args.char)
    except (FileNotFoundError, ValueError) as e:
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)

    # Subcommands, die kein .sav.zzip brauchen
    no_save_needed = {"log", "diary", "zones", "world"}

    save = {}
    if args.subcommand not in no_save_needed:
        try:
            save = load_save_json(world_dir, prefix)
        except Exception as e:
            print(f"Fehler beim Laden des Savefiles: {e}", file=sys.stderr)
            sys.exit(1)

    result = {}
    try:
        if args.subcommand == "status":
            result = cmd_status(save)
        elif args.subcommand == "inventory":
            result = cmd_inventory(save)
        elif args.subcommand == "skills":
            result = cmd_skills(save)
        elif args.subcommand == "traits":
            result = cmd_traits(save)
        elif args.subcommand == "log":
            result = cmd_log(world_dir, prefix)
        elif args.subcommand == "diary":
            result = cmd_diary(world_dir, prefix)
        elif args.subcommand == "zones":
            result = cmd_zones(world_dir, prefix)
        elif args.subcommand == "world":
            result = cmd_world(world_dir)
        elif args.subcommand == "raw":
            result = cmd_raw(save)
    except Exception as e:
        print(f"Fehler bei '{args.subcommand}': {e}", file=sys.stderr)
        sys.exit(1)

    indent = args.indent if args.indent > 0 else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
