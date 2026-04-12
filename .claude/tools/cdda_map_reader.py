#!/usr/bin/env python3
"""CDDA Map Reader — liest die gesehene Karte aus mm1-Map-Memory-Dateien.

Gibt Terrain und Furniture im sichtbaren Radius um den Spieler als JSON aus.
"""

import argparse
import base64
import json
import os
import struct
import sys
from collections import Counter
from pathlib import Path

try:
    import pyzstd
except ImportError:
    print("Fehler: pyzstd nicht installiert. Bitte: pip install pyzstd", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
SUBMAP_SIZE = 12        # 12x12 Tiles pro Submap
CACHE_DIM = 8           # 8x8 Submaps pro mm1-Cache
CACHE_TILES = CACHE_DIM * SUBMAP_SIZE  # 96 Tiles je Achse

# Terrain-Kategorien für lesbare Zusammenfassung
TERRAIN_CATEGORIES = {
    "gebaeude": {
        "t_floor", "t_floor_waxed", "t_floor_cement", "t_floor_glass",
        "t_wall_gray", "t_wall_g", "t_wall_wood", "t_wall_metal",
        "t_door_c", "t_door_o", "t_door_locked", "t_door_glass_c",
        "t_window_domestic", "t_window_boarded", "t_curtains",
        "t_stairs_up", "t_stairs_down",
    },
    "strasse": {
        "t_pavement", "t_pavement_y", "t_sidewalk", "t_road",
        "t_asphalt", "t_gutter",
    },
    "natur": {
        "t_grass", "t_grass_long", "t_grass_dead", "t_grass_golf",
        "t_dirt", "t_sand", "t_clay", "t_moss",
        "t_forestfloor", "t_forestfloor_no_litter",
    },
    "wald": {
        "t_tree", "t_tree_young", "t_tree_dead", "t_tree_deadtree",
        "t_tree_basswood", "t_tree_hazelnut", "t_tree_hickory",
        "t_tree_apple", "t_tree_cherry", "t_tree_birch",
        "t_tree_willow", "t_tree_pine", "t_tree_maple",
        "t_trunk", "t_stump", "t_underbrush", "t_shrub",
    },
    "wasser": {
        "t_water_sh", "t_water_dp", "t_water_moving_sh",
        "t_water_moving_dp", "t_pond", "t_river",
        "t_swater_sh", "t_swater_dp",
    },
}

NOTABLE_FURNITURE = {
    "f_bulletin_evac": "Evakuierungs-Schwarzes Brett",
    "f_bulletin": "Schwarzes Brett",
    "f_bed": "Bett",
    "f_makeshift_bed": "Notbett",
    "f_bench": "Sitzbank",
    "f_table": "Tisch",
    "f_workbench": "Werkbank",
    "f_rack": "Regal",
    "f_rack_empty": "Leeres Regal",
    "f_locker": "Spind",
    "f_locker_open": "Offener Spind",
    "f_cupboard": "Schrank",
    "f_cabinet": "Schrank",
    "f_fridge": "Kühlschrank",
    "f_freezer": "Gefrierschrank",
    "f_oven": "Ofen",
    "f_stove": "Herd",
    "f_sink": "Waschbecken",
    "f_toilet": "Toilette",
    "f_bathtub": "Badewanne",
    "f_generator": "Generator",
    "f_safe_c": "Tresor (geschlossen)",
    "f_safe_o": "Tresor (offen)",
    "f_gun_safe_c": "Waffenschrank",
    "f_gun_safe_o": "Waffenschrank (offen)",
    "f_woodstove": "Holzofen",
    "f_fireplace": "Kamin",
    "f_camp_fire": "Lagerfeuer",
}

# ---------------------------------------------------------------------------
# .env / Pfad-Hilfsfunktionen
# ---------------------------------------------------------------------------

def load_env(project_root: Path) -> dict:
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


def decode_char_name(encoded: str) -> str:
    b64 = encoded.lstrip("#")
    try:
        return base64.b64decode(b64 + "==").decode("utf-8")
    except Exception:
        return encoded


def find_world_dir(save_root: Path, world: str | None) -> Path:
    if world:
        candidate = save_root / world
        if not candidate.is_dir():
            for d in save_root.iterdir():
                if d.is_dir() and d.name.lower() == world.lower():
                    return d
            raise FileNotFoundError(f"Welt '{world}' nicht gefunden")
        return candidate
    worlds = [d for d in save_root.iterdir() if d.is_dir()]
    if not worlds:
        raise FileNotFoundError(f"Keine Welten in {save_root}")
    if len(worlds) > 1:
        raise ValueError(f"Mehrere Welten: {[w.name for w in worlds]}. --world angeben.")
    return worlds[0]


def find_char_prefix(world_dir: Path, char_name: str | None) -> str:
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
            raise ValueError(f"Charakter '{char_name}' nicht gefunden")
        return chars[char_name]
    if len(chars) > 1:
        raise ValueError(f"Mehrere Charaktere: {list(chars)}. --char angeben.")
    return next(iter(chars.values()))


# ---------------------------------------------------------------------------
# Savegame laden (für Spielerposition)
# ---------------------------------------------------------------------------

def decompress_zzip(path: Path, zstd_dict=None) -> bytes:
    """Dekomprimiert CDDA .zzip — mit oder ohne Dictionary."""
    data = path.read_bytes()
    offset = data.find(ZSTD_MAGIC)
    if offset == -1:
        raise ValueError(f"Kein zstd-Frame in {path}")
    dctx = pyzstd.ZstdDecompressor(zstd_dict=zstd_dict) if zstd_dict else pyzstd.ZstdDecompressor()
    return dctx.decompress(data[offset:], max_length=50 * 1024 * 1024)


def load_player_location(world_dir: Path, prefix: str) -> tuple[int, int, int]:
    """Lädt Spielerposition [x, y, z] aus dem Savegame."""
    sav_path = world_dir / f"{prefix}.sav.zzip"
    raw = decompress_zzip(sav_path)
    save = json.loads(raw)
    loc = save.get("player", {}).get("location", [0, 0, 0])
    return int(loc[0]), int(loc[1]), int(loc[2])


# ---------------------------------------------------------------------------
# mm1 Map-Memory lesen
# ---------------------------------------------------------------------------

def decode_rle_submap(cells: list) -> list[dict]:
    """Dekodiert RLE-kodierte Submap-Zellen in eine flache Liste von 144 Tiles.

    Zellenformat: [count, extra, terrain_id, param1, param2, furniture_id?, param?]
    """
    tiles = []
    for cell in cells:
        count = cell[0]
        terrain = cell[2] if len(cell) > 2 else ""
        furniture = cell[5] if len(cell) > 5 else ""
        for _ in range(count):
            tiles.append({"terrain": terrain, "furniture": furniture})
    return tiles


def load_mm1_cache(world_dir: Path, prefix: str, player_z: int = 0):
    """Lädt den mm1 warm-Cache und gibt ein 2D-Array von Tiles zurück.

    Gibt zurück: (tile_grid, base_world_x, base_world_y)
    tile_grid[y][x] = {"terrain": str, "furniture": str}
    """
    mm1_dir = world_dir / f"{prefix}.mm1"
    dict_path = world_dir / "mmr.dict"

    if not mm1_dir.exists():
        raise FileNotFoundError(f"mm1-Verzeichnis nicht gefunden: {mm1_dir}")
    if not dict_path.exists():
        raise FileNotFoundError(f"mmr.dict nicht gefunden: {dict_path}")

    mmr_dict = pyzstd.ZstdDict(dict_path.read_bytes())

    # Versuche warm → cold → hot
    cache_file = None
    for variant in ("warm", "cold", "hot"):
        candidate = mm1_dir / f"{prefix}.mm1.{variant}.zzip"
        if candidate.exists() and candidate.stat().st_size > 200:
            try:
                raw = candidate.read_bytes()
                offset = raw.find(ZSTD_MAGIC)
                if offset >= 0:
                    dctx = pyzstd.ZstdDecompressor(zstd_dict=mmr_dict)
                    data = dctx.decompress(raw[offset:], max_length=50 * 1024 * 1024)
                    parsed = json.loads(data)
                    if parsed.get("data"):
                        cache_file = parsed
                        break
            except Exception:
                continue

    if cache_file is None:
        raise ValueError("Kein lesbarer mm1-Cache gefunden")

    entries = cache_file["data"]  # Liste mit 64 Einträgen (oder None)

    # Alle 144-Tile-Submaps dekodieren
    submaps = []
    for entry in entries:
        if entry is None:
            submaps.append(None)
        else:
            tiles = decode_rle_submap(entry)
            if len(tiles) == SUBMAP_SIZE * SUBMAP_SIZE:
                submaps.append(tiles)
            else:
                submaps.append(None)

    return submaps


def find_cache_base(submaps: list, player_x: int, player_y: int) -> tuple[int, int]:
    """Ermittelt die Basis-Weltkoordinate des Caches.

    Der Cache ist 8x8 Submaps (à 12x12 Tiles). Der Spieler liegt irgendwo
    darin. Wir suchen den Grid-Offset des Spielers, indem wir testen welcher
    col/row für den Spieler-Submap auf einen nicht-leeren Eintrag passt.
    """
    player_sx = player_x // SUBMAP_SIZE  # Submap-Koordinate des Spielers
    player_sy = player_y // SUBMAP_SIZE

    # base_x ist immer 8-aligned (CDDA-Cache ist 8x8-Submap-aligned auf x)
    base_x_sm = (player_sx // CACHE_DIM) * CACHE_DIM
    player_col = player_sx - base_x_sm

    # base_y suchen: probiere alle 8 Zeilen
    for player_row in range(CACHE_DIM):
        base_y_sm = player_sy - player_row
        idx = player_col + player_row * CACHE_DIM
        if 0 <= idx < len(submaps) and submaps[idx] is not None:
            return base_x_sm * SUBMAP_SIZE, base_y_sm * SUBMAP_SIZE

    # Fallback: 8-aligned
    return base_x_sm * SUBMAP_SIZE, (player_sy // CACHE_DIM) * CACHE_DIM * SUBMAP_SIZE


def build_tile_grid(submaps: list, base_wx: int, base_wy: int) -> list[list[dict]]:
    """Baut ein 96×96 Tile-Grid aus den 64 Submaps auf."""
    grid = [[{"terrain": "", "furniture": ""} for _ in range(CACHE_TILES)]
            for _ in range(CACHE_TILES)]

    for sm_idx, sm in enumerate(submaps):
        if sm is None:
            continue
        sm_col = sm_idx % CACHE_DIM
        sm_row = sm_idx // CACHE_DIM
        origin_x = sm_col * SUBMAP_SIZE
        origin_y = sm_row * SUBMAP_SIZE

        for tile_idx, tile in enumerate(sm):
            tx = origin_x + (tile_idx % SUBMAP_SIZE)
            ty = origin_y + (tile_idx // SUBMAP_SIZE)
            if 0 <= ty < CACHE_TILES and 0 <= tx < CACHE_TILES:
                grid[ty][tx] = tile

    return grid


# ---------------------------------------------------------------------------
# Analyse-Funktionen
# ---------------------------------------------------------------------------

def categorize_terrain(terrain_id: str) -> str:
    for category, ids in TERRAIN_CATEGORIES.items():
        if terrain_id in ids:
            return category
    if terrain_id:
        return "sonstiges"
    return "unbekannt"


def analyze_radius(
    grid: list[list[dict]],
    base_wx: int,
    base_wy: int,
    player_x: int,
    player_y: int,
    radius: int = 20,
) -> dict:
    """Analysiert Terrain und Furniture im gegebenen Radius um den Spieler."""
    # Spielerposition im Grid
    px_in_grid = player_x - base_wx
    py_in_grid = player_y - base_wy

    terrain_counts = Counter()
    category_counts = Counter()
    notable = []  # (dx, dy, furniture_id, label)
    terrain_by_direction = {"N": Counter(), "S": Counter(), "O": Counter(), "W": Counter()}

    seen_tiles = 0

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > radius:
                continue

            gx = px_in_grid + dx
            gy = py_in_grid + dy

            if not (0 <= gx < CACHE_TILES and 0 <= gy < CACHE_TILES):
                continue

            tile = grid[gy][gx]
            terrain = tile["terrain"]
            furniture = tile["furniture"]

            if not terrain and not furniture:
                continue  # ungesehenes Tile

            seen_tiles += 1
            terrain_counts[terrain] += 1
            category_counts[categorize_terrain(terrain)] += 1

            # Richtungsaufteilung
            if abs(dy) > abs(dx):
                direction = "N" if dy < 0 else "S"
            else:
                direction = "W" if dx < 0 else "O"
            terrain_by_direction[direction][categorize_terrain(terrain)] += 1

            # Notable Furniture
            if furniture in NOTABLE_FURNITURE:
                notable.append({
                    "dx": dx,
                    "dy": dy,
                    "distance": round(dist, 1),
                    "furniture": furniture,
                    "label": NOTABLE_FURNITURE[furniture],
                    "direction": _compass(dx, dy),
                })

    # Sortiere Notable nach Distanz
    notable.sort(key=lambda e: e["distance"])

    return {
        "player_position": [player_x, player_y],
        "radius": radius,
        "seen_tiles": seen_tiles,
        "terrain_counts": dict(terrain_counts.most_common(20)),
        "category_counts": dict(category_counts),
        "direction_summary": {d: dict(c.most_common(5)) for d, c in terrain_by_direction.items()},
        "notable_furniture": notable,
    }


def _compass(dx: int, dy: int) -> str:
    """Himmelsrichtung für einen Offset."""
    if dx == 0 and dy == 0:
        return "hier"
    angle_map = [
        (22.5, "O"), (67.5, "SO"), (112.5, "S"), (157.5, "SW"),
        (202.5, "W"), (247.5, "NW"), (292.5, "N"), (337.5, "NO"), (360, "O"),
    ]
    import math
    deg = math.degrees(math.atan2(dy, dx)) % 360
    for threshold, label in angle_map:
        if deg <= threshold:
            return label
    return "O"


def render_ascii(
    grid: list[list[dict]],
    base_wx: int,
    base_wy: int,
    player_x: int,
    player_y: int,
    radius: int = 20,
    width: int = 60,
    height: int = 30,
) -> str:
    """Rendert eine ASCII-Karte im gegebenen Radius."""
    SYMBOLS = {
        # Gebäude
        "t_floor": ".", "t_wall_gray": "#", "t_wall_g": "#",
        "t_wall_wood": "#", "t_wall_metal": "#",
        "t_door_c": "+", "t_door_o": "/",
        "t_window_domestic": "=", "t_curtains": "=",
        "t_stairs_up": "<", "t_stairs_down": ">",
        # Strasse
        "t_pavement": "_", "t_sidewalk": "_", "t_road": "_",
        # Natur
        "t_grass": ",", "t_grass_long": ";", "t_grass_dead": ".",
        "t_dirt": "·", "t_sand": "~", "t_moss": ",",
        "t_forestfloor": ",",
        # Wald
        "t_tree": "T", "t_tree_young": "t", "t_tree_dead": "t",
        "t_tree_basswood": "T", "t_tree_hazelnut": "T",
        "t_tree_hickory": "T", "t_tree_pine": "T",
        "t_trunk": "=", "t_stump": "o", "t_underbrush": "%", "t_shrub": "%",
        # Wasser
        "t_water_sh": "~", "t_water_dp": "≈",
    }
    FURNITURE_SYMBOLS = {
        "f_bed": "b", "f_locker": "L", "f_cupboard": "c",
        "f_rack": "r", "f_workbench": "W", "f_table": "τ",
        "f_toilet": "T", "f_sink": "s", "f_fridge": "F",
        "f_bulletin_evac": "!", "f_bulletin": "!",
        "f_bench": "n", "f_safe_c": "S", "f_generator": "G",
    }

    px_in_grid = player_x - base_wx
    py_in_grid = player_y - base_wy

    # Skalierung: width/height Zeichen sollen radius*2 Tiles abdecken
    scale_x = (radius * 2 + 1) / width
    scale_y = (radius * 2 + 1) / height

    lines = []
    for row in range(height):
        line = []
        for col in range(width):
            # Tile-Koordinaten im Grid
            dx = int((col - width // 2) * scale_x)
            dy = int((row - height // 2) * scale_y)
            gx = px_in_grid + dx
            gy = py_in_grid + dy

            # Spieler-Symbol
            if dx == 0 and dy == 0:
                line.append("@")
                continue

            if not (0 <= gx < CACHE_TILES and 0 <= gy < CACHE_TILES):
                line.append(" ")
                continue

            tile = grid[gy][gx]
            terrain = tile["terrain"]
            furniture = tile["furniture"]

            if not terrain and not furniture:
                line.append(" ")
                continue

            char = FURNITURE_SYMBOLS.get(furniture) or SYMBOLS.get(terrain, "?")
            line.append(char)

        lines.append("".join(line))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CDDA Map Reader — gibt gesehene Karte als JSON aus"
    )
    parser.add_argument("--world", help="Weltname")
    parser.add_argument("--char", help="Charaktername")
    parser.add_argument(
        "--radius", type=int, default=20,
        help="Analyse-Radius in Tiles (Standard: 20)"
    )
    parser.add_argument(
        "--ascii", action="store_true",
        help="ASCII-Karte zusätzlich ausgeben"
    )
    parser.add_argument(
        "--ascii-width", type=int, default=60,
        help="Breite der ASCII-Karte"
    )
    parser.add_argument(
        "--ascii-height", type=int, default=30,
        help="Höhe der ASCII-Karte"
    )
    parser.add_argument(
        "--indent", type=int, default=2,
        help="JSON-Einrückung (0 = kompakt)"
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    env = load_env(project_root)
    cdda_root = env.get("CDDA_ROOT") or os.environ.get("CDDA_ROOT")
    if not cdda_root:
        print("Fehler: CDDA_ROOT nicht gesetzt.", file=sys.stderr)
        sys.exit(1)

    save_root = Path(cdda_root) / "save"
    try:
        world_dir = find_world_dir(save_root, args.world)
        prefix = find_char_prefix(world_dir, args.char)
    except (FileNotFoundError, ValueError) as e:
        print(f"Fehler: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        player_x, player_y, player_z = load_player_location(world_dir, prefix)
    except Exception as e:
        print(f"Fehler beim Laden der Spielerposition: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        submaps = load_mm1_cache(world_dir, prefix, player_z)
    except Exception as e:
        print(f"Fehler beim Laden des mm1-Caches: {e}", file=sys.stderr)
        sys.exit(1)

    base_wx, base_wy = find_cache_base(submaps, player_x, player_y)
    grid = build_tile_grid(submaps, base_wx, base_wy)
    result = analyze_radius(grid, base_wx, base_wy, player_x, player_y, args.radius)

    if args.ascii:
        ascii_map = render_ascii(
            grid, base_wx, base_wy, player_x, player_y,
            radius=args.radius,
            width=args.ascii_width,
            height=args.ascii_height,
        )
        result["ascii_map"] = ascii_map

    indent = args.indent if args.indent > 0 else None
    print(json.dumps(result, ensure_ascii=False, indent=indent))


if __name__ == "__main__":
    main()
