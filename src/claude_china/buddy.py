"""
Claude Code Buddy system — ported from claude-code/src/buddy/

Deterministic companion generation using Mulberry32 PRNG seeded by a string hash.
Each seed produces a unique buddy with species, rarity, eyes, hat, stats, and ASCII sprite.
"""

import json
import os
import random
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- Constants ---

RARITIES = ["common", "uncommon", "rare", "epic", "legendary"]

RARITY_WEIGHTS = {
    "common": 60,
    "uncommon": 25,
    "rare": 10,
    "epic": 4,
    "legendary": 1,
}

RARITY_STARS = {
    "common": "★",
    "uncommon": "★★",
    "rare": "★★★",
    "epic": "★★★★",
    "legendary": "★★★★★",
}

RARITY_COLORS = {
    "common": "white",
    "uncommon": "green",
    "rare": "blue",
    "epic": "magenta",
    "legendary": "yellow",
}

SPECIES = [
    "duck", "goose", "blob", "cat", "dragon", "octopus", "owl", "penguin",
    "turtle", "snail", "ghost", "axolotl", "capybara", "cactus", "robot",
    "rabbit", "mushroom", "chonk",
]

EYES = ["·", "✦", "×", "◉", "@", "°"]

HATS = ["none", "crown", "tophat", "propeller", "halo", "wizard", "beanie", "tinyduck"]

STAT_NAMES = ["DEBUGGING", "PATIENCE", "CHAOS", "WISDOM", "SNARK"]

RARITY_FLOOR = {
    "common": 5,
    "uncommon": 15,
    "rare": 25,
    "epic": 35,
    "legendary": 50,
}

SALT = "friend-2026-401"

# --- JS 32-bit arithmetic helpers ---

import ctypes

def _i32(x):
    """Convert to signed 32-bit integer (JS `|0` / `Math.imul` semantics)."""
    return ctypes.c_int32(x & 0xFFFFFFFF).value

def _u32(x):
    """Convert to unsigned 32-bit integer (JS `>>> 0` semantics)."""
    return x & 0xFFFFFFFF

def _imul(a, b):
    """JS Math.imul — signed 32-bit multiply, truncated to low 32 bits."""
    return _i32(_i32(a) * _i32(b))


# --- PRNG (Mulberry32) ---

def mulberry32(seed: int):
    """Mulberry32 PRNG — matching the JS implementation exactly.

    JS uses signed 32-bit ops (`|= 0`, `Math.imul`), unsigned shifts (`>>> 0`).
    """
    a = _i32(seed)

    def next_rand():
        nonlocal a
        a = _i32(a + 0x6D2B79F5)
        t = _imul(a ^ (_u32(a) >> 15), _i32(1 | a))
        t = _i32(t + _imul(t ^ (_u32(t) >> 7), _i32(61 | t))) ^ t
        return _u32(t ^ (_u32(t) >> 14)) / 4294967296

    return next_rand


def hash_string(s: str) -> int:
    """FNV-1a hash, matching the JS fallback (non-Bun) implementation."""
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


# --- Data structures ---

@dataclass
class CompanionBones:
    rarity: str
    species: str
    eye: str
    hat: str
    shiny: bool
    stats: Dict[str, int]


# --- Generation logic ---

def pick(rng, arr):
    return arr[int(rng() * len(arr))]


def roll_rarity(rng) -> str:
    total = sum(RARITY_WEIGHTS.values())
    roll = rng() * total
    for rarity in RARITIES:
        roll -= RARITY_WEIGHTS[rarity]
        if roll < 0:
            return rarity
    return "common"


def roll_stats(rng, rarity: str) -> Dict[str, int]:
    floor = RARITY_FLOOR[rarity]
    peak = pick(rng, STAT_NAMES)
    dump = pick(rng, STAT_NAMES)
    while dump == peak:
        dump = pick(rng, STAT_NAMES)

    stats = {}
    for name in STAT_NAMES:
        if name == peak:
            stats[name] = min(100, floor + 50 + int(rng() * 30))
        elif name == dump:
            stats[name] = max(1, floor - 10 + int(rng() * 15))
        else:
            stats[name] = floor + int(rng() * 40)
    return stats


def roll_bones(rng) -> CompanionBones:
    rarity = roll_rarity(rng)
    return CompanionBones(
        rarity=rarity,
        species=pick(rng, SPECIES),
        eye=pick(rng, EYES),
        hat="none" if rarity == "common" else pick(rng, HATS),
        shiny=rng() < 0.01,
        stats=roll_stats(rng, rarity),
    )


def roll_from_seed(seed: str) -> CompanionBones:
    """Roll a buddy from a string seed."""
    rng = mulberry32(hash_string(seed))
    return roll_bones(rng)


def roll_by_name(name: str) -> CompanionBones:
    """Roll a buddy seeded by profile name + salt (matches Claude Code behavior)."""
    return roll_from_seed(name + SALT)


def roll_random() -> CompanionBones:
    """Roll a completely random buddy."""
    seed = str(random.randint(0, 2**32))
    return roll_from_seed(seed + SALT)


def _quick_check(user_id: str, target_rarity: str = None, target_species: str = None) -> bool:
    """Fast check: only roll rarity (and species if needed) without full bones generation."""
    rng = mulberry32(hash_string(user_id + SALT))
    rarity = roll_rarity(rng)
    if target_rarity and rarity != target_rarity:
        return False
    if target_species:
        species = pick(rng, SPECIES)
        if species != target_species:
            return False
    return True


def bruteforce_user_id(
    target_rarity: str = None,
    target_species: str = None,
    max_attempts: int = 5_000_000,
) -> Tuple[str, CompanionBones]:
    """Bruteforce a userID that produces the desired buddy.

    Returns (user_id, bones) tuple.
    """
    for i in range(max_attempts):
        user_id = secrets.token_hex(16)
        if not _quick_check(user_id, target_rarity, target_species):
            continue
        bones = roll_from_seed(user_id + SALT)
        return user_id, bones
    raise RuntimeError(f"Failed to find matching userID after {max_attempts} attempts")


def get_claude_config_path(config_dir: Optional[str] = None) -> Path:
    """Get the .claude.json path for a given config directory.

    Claude Code reads from: $CLAUDE_CONFIG_DIR/.claude.json (if set) or ~/.claude.json
    Login mode profiles set CLAUDE_CONFIG_DIR=credentials_path.
    API mode profiles don't set it, so use ~/.claude.json.
    """
    base = Path(config_dir) if config_dir else Path.home()
    return base / ".claude.json"


def read_claude_config(config_dir: Optional[str] = None) -> dict:
    path = get_claude_config_path(config_dir)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_user_id_to_claude_config(user_id: str, config_dir: Optional[str] = None):
    """Write userID to .claude.json, preserving other fields.

    Also removes oauthAccount.accountUuid so Claude Code falls back to userID.
    """
    path = get_claude_config_path(config_dir)
    config = read_claude_config(config_dir)
    config["userID"] = user_id
    # Remove accountUuid so buddy uses userID
    if "oauthAccount" in config and "accountUuid" in config["oauthAccount"]:
        del config["oauthAccount"]["accountUuid"]
        if not config["oauthAccount"]:
            del config["oauthAccount"]
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def roll_until_match(
    target_rarity: str = None,
    target_species: str = None,
    max_attempts: int = 100000,
) -> CompanionBones:
    """Keep rolling random buddies until we match the target criteria (display only)."""
    for _ in range(max_attempts):
        bones = roll_random()
        if target_rarity and bones.rarity != target_rarity:
            continue
        if target_species and bones.species != target_species:
            continue
        return bones
    return roll_random()


def roll_until_rarity(target_rarity: str, max_attempts: int = 100000) -> CompanionBones:
    return roll_until_match(target_rarity=target_rarity, max_attempts=max_attempts)


# --- ASCII Sprites ---

# Each sprite: 5 lines tall, 12 wide. {E} replaced with eye character.
BODIES = {
    "duck": [
        '            ',
        '    __      ',
        '  <({E} )___  ',
        '   (  ._>   ',
        '    `--´    ',
    ],
    "goose": [
        '            ',
        '     ({E}>    ',
        '     ||     ',
        '   _(__)_   ',
        '    ^^^^    ',
    ],
    "blob": [
        '            ',
        '   .----.   ',
        '  ( {E}  {E} )  ',
        '  (      )  ',
        '   `----´   ',
    ],
    "cat": [
        '            ',
        '   /\\_/\\    ',
        '  ( {E}   {E})  ',
        '  (  ω  )   ',
        '  (")_(")   ',
    ],
    "dragon": [
        '            ',
        '  /^\\  /^\\  ',
        ' <  {E}  {E}  > ',
        ' (   ~~   ) ',
        '  `-vvvv-´  ',
    ],
    "octopus": [
        '            ',
        '   .----.   ',
        '  ( {E}  {E} )  ',
        '  (______)  ',
        '  /\\/\\/\\/\\  ',
    ],
    "owl": [
        '            ',
        '   /\\  /\\   ',
        '  (({E})({E}))  ',
        '  (  ><  )  ',
        '   `----´   ',
    ],
    "penguin": [
        '            ',
        '  .---.     ',
        '  ({E}>{E})     ',
        ' /(   )\\    ',
        '  `---´     ',
    ],
    "turtle": [
        '            ',
        '   _,--._   ',
        '  ( {E}  {E} )  ',
        ' /[______]\\ ',
        '  ``    ``  ',
    ],
    "snail": [
        '            ',
        ' {E}    .--.  ',
        '  \\  ( @ )  ',
        '   \\_`--´   ',
        '  ~~~~~~~   ',
    ],
    "ghost": [
        '            ',
        '   .----.   ',
        '  / {E}  {E} \\  ',
        '  |      |  ',
        '  ~`~``~`~  ',
    ],
    "axolotl": [
        '            ',
        '}~(______)~{',
        '}~({E} .. {E})~{',
        '  ( .--. )  ',
        '  (_/  \\_)  ',
    ],
    "capybara": [
        '            ',
        '  n______n  ',
        ' ( {E}    {E} ) ',
        ' (   oo   ) ',
        '  `------´  ',
    ],
    "cactus": [
        '            ',
        ' n  ____  n ',
        ' | |{E}  {E}| | ',
        ' |_|    |_| ',
        '   |    |   ',
    ],
    "robot": [
        '            ',
        '   .[||].   ',
        '  [ {E}  {E} ]  ',
        '  [ ==== ]  ',
        '  `------´  ',
    ],
    "rabbit": [
        '            ',
        '   (\\__/)   ',
        '  ( {E}  {E} )  ',
        ' =(  ..  )= ',
        '  (")__(")  ',
    ],
    "mushroom": [
        '            ',
        ' .-o-OO-o-. ',
        '(__________)',
        '   |{E}  {E}|   ',
        '   |____|   ',
    ],
    "chonk": [
        '            ',
        '  /\\    /\\  ',
        ' ( {E}    {E} ) ',
        ' (   ..   ) ',
        '  `------´  ',
    ],
}

HAT_LINES = {
    "none": "",
    "crown": "   \\^^^/    ",
    "tophat": "   [___]    ",
    "propeller": "    -+-     ",
    "halo": "   (   )    ",
    "wizard": "    /^\\     ",
    "beanie": "   (___)    ",
    "tinyduck": "    ,>      ",
}


def render_sprite(bones: CompanionBones) -> List[str]:
    """Render the ASCII sprite for a buddy."""
    body = BODIES[bones.species]
    lines = [line.replace("{E}", bones.eye) for line in body]
    # Replace hat line if species has blank first line
    if bones.hat != "none" and not lines[0].strip():
        lines[0] = HAT_LINES[bones.hat]
    # Drop blank hat slot if unused
    if not lines[0].strip():
        lines = lines[1:]
    return lines


# --- Display ---

def format_stat_bar(name: str, value: int) -> str:
    """Format a single stat as a labeled bar."""
    bar_len = value // 5  # 0-20 chars
    bar = "█" * bar_len + "░" * (20 - bar_len)
    return f"  {name:<10} {bar} {value:>3}"


def format_buddy_card(bones: CompanionBones) -> str:
    """Format a full buddy card for terminal display."""
    lines = []

    # Sprite
    sprite = render_sprite(bones)
    for s in sprite:
        lines.append(f"    {s}")

    lines.append("")

    # Info
    shiny_tag = " ✨ SHINY" if bones.shiny else ""
    stars = RARITY_STARS[bones.rarity]
    lines.append(f"  Species:  {bones.species.capitalize()}")
    lines.append(f"  Rarity:   {bones.rarity.capitalize()} {stars}{shiny_tag}")
    lines.append(f"  Eyes:     {bones.eye}")
    if bones.hat != "none":
        lines.append(f"  Hat:      {bones.hat.capitalize()}")

    lines.append("")
    lines.append("  ── Stats ──")
    for stat_name in STAT_NAMES:
        lines.append(format_stat_bar(stat_name, bones.stats[stat_name]))

    return "\n".join(lines)
