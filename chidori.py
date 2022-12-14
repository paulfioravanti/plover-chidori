"""
Chidori - A Japanese dictionary for Plover.

Primarily converts a steno chord into a romaji string to be used as input
for an Input Method Editor (IME) like:
- Google Japanese input IME (https://www.google.co.jp/ime/)
- Kotoeri (https://en.wikipedia.org/wiki/Kotoeri)
"""

import re
from functools import reduce, lru_cache
from typing import Any, List, Optional, Tuple

# Length of the longest supported key (number of strokes).
LONGEST_KEY = 1

_STANDALONE_COMMANDS = {
    # COMMANDS
    # No spaces in Japanese means star cannot delete by "word".
    "*": "{#BACKSPACE}{^}",
    # IME-Specific command helpers
    "S*P": "{#SHIFT_L(SPACE)}",
    "S-P": "{#SPACE}",
    "W*B": "{#SHIFT_L(SPACE)}",
    "W-B": "{#SPACE}",
    # PUNCTUATION
    "TKABGT": "{^゙^}",   # DAKuTen 濁点
    "TKHABGT": "{^゚^}"   # HanDAKuTen 半濁点
}
_STANDALONE_OUTPUT = {
    # PUNCTUATION
    "#*D": "ヾ",        # katakana voiced iteration mark odoriji 踊り字
    "#-D": "ヽ",        # katakana iteration mark odoriji 踊り字
    "*D": "ゞ",         # hiragana voiced iteration mark odoriji 踊り字
    "-D": "ゝ",         # hiragana iteration mark odoriji 踊り字
    "-FPLT": ".",
    "-RBGS": ",",
    "H-F": "?",
    "H-PB": "-",
    "KO*T": "ヿ",       # polysyllabic kana for 事
    "K*UPBLG": "〱",    # KUnoJiten くの字点
    "TKPW*UPBLG": "〲", # GUnoJiten (with dakuten) くの字点
    "O*EU": "/",
    "PR-PB": "(",
    "PR*PB": ")",
    "PWR-BGT": "[",
    "PWR*BGT": "]",
    "STPH-FPLT": ":",
    "STPH*FPLT": ";",
    "T*LD": "~",
    "TP-BG": "!",
    # ROMAJI
    "H": "ha", # は
    "HR": "ra", # ら
    "K": "ku", # く
    "KP": "za", # ざ
    "KR": "ku", # く
    "KW": "kyu", # きゅ
    "KWA*": "kuxwa", # くゎ
    "KWR": "ya", # や
    "P": "pu", # ぷ
    "PH": "ma", # ま
    "PW": "bu", # ぶ
    "R": "ru", # る
    "S": "su", # す
    "SKWR": "ji", # じ
    "SR": "vu", # ゔ
    "STKPW": "zu", # ず
    "T": "tu", # つ
    "T-T": "tta", # った
    "TK": "du", # づ
    "TKPW": "gu", # ぐ
    "TP": "fu", # ふ
    "TPH": "nn", # ん
    "W": "wa", # わ
}

_HYPHEN = "-"
_STAR = "*"

_CHORD_PARTS = re.compile(
    rf"([STKPWHR]*)([{_HYPHEN}AO{_STAR}EU]*)([FRPBLGTSDZ]*)"
)

_VOWELS_ROMAJI = ("EU", "i") # い

_EXCEPTION_CHORDS = [
    (
        # Z-Chord: ざ…
        re.compile(rf"S([AO]+[{_STAR}]|[{_STAR}][EU]+)"),
        lambda vowels : _exception_chord_romaji("z", vowels)
    ),
    (
        # Wi/We Chord: ゐ/ヰ, ゑ/ヱ
        # https://en.wikipedia.org/wiki/Wi_(kana)
        # https://en.wikipedia.org/wiki/We_(kana)
        re.compile(rf"W[{_STAR}](E|EU)"),
        lambda vowels : _exception_chord_romaji("wy", vowels)
    ),
    (
        # TI Chord: てぃ
        re.compile(r"^TEU$"),
        lambda _vowels : "texi"
    )
]

_INITIAL_ROMAJI = {
    # single character/compound chords
    "TP": "f", # ふぁ…
    "PH": "m", # ま…
    "KWR": "y", # や…
    "TPH": "n", # な…
    "TKPW": "g", # が…
    "STKPW": "z", # ざ…
    "TK": "d", # だ…
    "PW": "b", # ば…
    "KR": "ky", # きゃ…
    "TKPWR": "gy", # ぎゃ…
    "TPHR": "ny", # にゃ…
    "HR": "hy", # ひゃ…
    "PWR": "by", # びゃ…
    "PR": "py", # ぴゃ…
    "PHR": "my", # みゃ…
    "WR": "ry", # りゃ…
    "SKWR": "j", # じゃ…
    "KH": "ch", # ちゃ…
    "SR": "v", # ゔぁ…
    # Multi-full-size-character chords: devoiced/abbreviated characters
    # ku
    "KPH": "kum", # く+ま…
    "KW": "kuw", # く+わ…
    "KPW": "kub", # く+ば…
    # su
    "SK": "suk", # す+か…
    "STP": "suf", # す+ふぁ…
    "SPH": "sum", # す+ま…
    "STPH": "sun", # す+な…
    "STK": "sud", # す+だ…
    "SPW": "sub", # す+ば…
    "SKR": "suky", # す+きゃ…
    "STKPWR": "sugy", # す+ぎゃ…
    "STPHR": "suny", # す+にゃ…
    "SHR": "suhy", # す+ひゃ…
    "SPWR": "suby", # す+びゃ…
    "SPR": "supy", # す+ぴゃ…
    "SPHR": "sumy", # す+みゃ…
    "SWR": "sury", # す+りゃ…
    "SKH": "such", # す+ちゃ…
    # fu
    "TPW": "fuw", # ふ+わ…
    "TPR": "fur", # ふ+ら…
}

# Hepburn romanisation used as a general rule, but Kunrei-shiki romanisation
# used if the number of characters output is less than Hepburn.
# NOTE: Order is important in this array.
_FINAL_ROMAJI = [
    ("FPL", "-"), # ー
    ("FP", "ti"), # ち
    ("RB", "si"), # し
    ("PBLG", "ji"), # じ
    ("PB", "nn"), # ん
    ("PL", "ma"), # ま
    ("BG", "ku"), # く
    ("TS", "tu"), # つ
    ("F", "fu"), # ふ
    ("R", "ru"), # る
    ("P", "pu"), # ぷ
    ("B", "bu"), # ぶ
    ("L", "xtu"), # っ
    ("G", "gu"), # ぐ
    ("T", "ta"), # た
    ("S", "su") # す
]

# https://en.wikipedia.org/wiki/Ch%C5%8Donpu
_PROLONGED_VOWEL_CHORD = "DZ" # かあ…
_PROLONGED_VOWEL_SMALL_CHARACTER_STROKE = ( # かぁ…
    re.compile(rf"[{_STAR}][A-z]*{_PROLONGED_VOWEL_CHORD}")
)

# https://en.wikipedia.org/wiki/Sokuon
_SMALL_CHARACTER_CHORD = "Z" # ぁ…
_SMALL_CHARACTER_ROMAJI_PREFIX = "x"

_REPEAT_CHARACTERS_CHORD = "D" # かか…
_REPEAT_CHARACTERS_STROKE = (
    re.compile(rf"[^{_STAR}]+{_REPEAT_CHARACTERS_CHORD}")
)

_REPEAT_CHARACTERS_DIACRITIC_STROKE = ( # かが…
    re.compile(rf"[{_STAR}][A-z]*{_REPEAT_CHARACTERS_CHORD}")
)
_EXCEPTION_DIACRITIC_SOUNDS = {
    "fu": "b", # ふ=>ぶ
    "chi": "d" # ち=>ぢ
}
# NOTE: Going from dakuten to handakuten is prioritised over going from dakuten
# to no diacritic, which means the following diacritic reversals are not
# possible: "b": "h", "by": "hy"
# https://en.wikipedia.org/wiki/Dakuten_and_handakuten
_DIACRITIC_SOUNDS = {
    "k": "g",
    "s": "z",
    "t": "d",
    "h": "b",
    "b": "p",
    "ky": "gy",
    "hy": "by",
    "by": "py",
    "ch": "dy",
    "sh": "j",
    # diacritic reversals
    "g": "k",
    "z": "s",
    "d": "t",
    "p": "b",
    "gy": "ky",
    "py": "by",
    "dy": "ch",
    "j": "sh"
}

_NON_VOWELS = re.compile(r"[^AEIOU]", re.IGNORECASE)
_VOWELS = re.compile(r"[AEIOU]", re.IGNORECASE)

# Lookup function: return the translation for <key> (a tuple of strokes)
# or raise KeyError if no translation is available/possible.
def lookup(key: List[str]) -> str:
    """
    Convert chorded Plover stroke into equivalent romaji
    """
    assert len(key) <= LONGEST_KEY
    stroke = key[0]

    if standalone_command := _STANDALONE_COMMANDS.get(stroke):
        return standalone_command

    if standalone_output := _STANDALONE_OUTPUT.get(stroke):
        return f'{{^{standalone_output}^}}'

    if not (chords := _CHORD_PARTS.match(stroke)):
        raise KeyError

    romaji = _convert_to_romaji(chords)

    if _is_invalid_romaji(romaji):
        raise KeyError

    return f'{{^{romaji}^}}'

# Optional: return an array of stroke tuples that would translate back
# to <text> (an empty array if not possible).
def reverse_lookup(_text: str) -> List[Any]:
    """
    No reverse lookup provided
    """
    return []

# PRIVATE

def _convert_to_romaji(chords: re.Match) -> str:
    initial, vowels, final = chords.group(1, 2, 3)
    initial = _initial_to_romaji(initial, vowels)
    return _final_to_romaji(initial, final)

def _initial_to_romaji(initial: str, vowels: str) -> str:
    if initial is None:
        return _vowels_to_romaji(vowels)

    if exception_chord := _exception_chords_to_romaji(initial, vowels):
        return exception_chord

    initial = _INITIAL_ROMAJI.get(initial) or initial.lower()
    vowels = _vowels_to_romaji(vowels)

    return initial + vowels

# https://docs.python.org/3/library/functools.html#functools.lru_cache
@lru_cache
def _vowels_to_romaji(vowels: str) -> str:
    return vowels.replace(*_VOWELS_ROMAJI).lower()

def _exception_chords_to_romaji(initial: str, vowels: str) -> Optional[str]:
    for exception_chord, exception_chord_handler in _EXCEPTION_CHORDS:
        if exception_chord.match(initial + vowels):
            return exception_chord_handler(vowels)

    return None

def _exception_chord_romaji(initial_character: str, vowels: str) -> str:
    vowels = _vowels_to_romaji(_remove_star(vowels))
    return initial_character + vowels

def _remove_star(string: str) -> str:
    return string.replace(_STAR, "")

def _final_to_romaji(initial: str, final: str) -> str:
    final = reduce(_chord_to_romaji, _FINAL_ROMAJI, final)
    initial = _remove_blank_chord(initial)

    if _has_prolonged_vowel_small_character_chord(initial + final):
        initial, final = _add_prolonged_vowel_small_character(initial, final)
    elif _has_prolonged_vowel_chord(final):
        final = _add_prolonged_vowel(initial, final)
    elif _has_small_character_chord(final):
        initial, final = _add_small_character(initial, final)
    elif _has_repeat_character_chord(initial + final):
        final = _add_repeated_characters(initial, final)
    elif _has_repeat_character_diacritic_chord(initial + final):
        initial, final = _add_repeated_diacritic_characters(initial, final)

    return initial + final

def _chord_to_romaji(acc: str, chord_romaji: Tuple[str, str]) -> str:
    return acc.replace(chord_romaji[0], chord_romaji[1])

def _remove_blank_chord(chord: str) -> str:
    if chord.startswith(_HYPHEN):
        return chord.replace(_HYPHEN, "")

    return chord

def _has_prolonged_vowel_small_character_chord(
    stroke: str
) -> Optional[re.Match]:
    return _PROLONGED_VOWEL_SMALL_CHARACTER_STROKE.search(stroke)

def _add_prolonged_vowel_small_character(
    initial: str,
    final: str
) -> Tuple[str, str]:
    initial = _remove_star(initial)
    final = final.replace(_PROLONGED_VOWEL_CHORD, "")
    final = final + _SMALL_CHARACTER_ROMAJI_PREFIX + (initial + final)[-1]
    return (initial, final)

def _has_prolonged_vowel_chord(chord: str) -> bool:
    return chord.endswith(_PROLONGED_VOWEL_CHORD)

def _add_prolonged_vowel(initial: str, final: str) -> str:
    final = final.replace(_PROLONGED_VOWEL_CHORD, "")
    return final + (initial + final)[-1]

def _has_small_character_chord(chord: str) -> bool:
    return chord.endswith(_SMALL_CHARACTER_CHORD)

def _add_small_character(initial: str, final: str) -> Tuple[str, str]:
    final = final.replace(_SMALL_CHARACTER_CHORD, "")
    initial = _SMALL_CHARACTER_ROMAJI_PREFIX + initial
    return (initial, final)

def _has_repeat_character_chord(stroke: str) -> Optional[re.Match]:
    return _REPEAT_CHARACTERS_STROKE.match(stroke)

def _add_repeated_characters(initial: str, final: str) -> str:
    return (final + initial + final).replace(_REPEAT_CHARACTERS_CHORD, "")

def _has_repeat_character_diacritic_chord(stroke: str) -> Optional[re.Match]:
    return _REPEAT_CHARACTERS_DIACRITIC_STROKE.search(stroke)

def _add_repeated_diacritic_characters(
    initial: str,
    final: str
) -> Tuple[str, str]:
    initial = _remove_star(initial)

    if diacritic := _diacritic_sound(initial):
        final = diacritic + re.sub(_NON_VOWELS, "", initial)
    elif diacritic := _diacritic_sound(final[:-1]):
        final = final.replace(_REPEAT_CHARACTERS_CHORD, "")
        final = final + diacritic + final[-1:]
    else:
        final = ""

    return (initial, final)

def _diacritic_sound(initial: str) -> Optional[str]:
    return (
        _EXCEPTION_DIACRITIC_SOUNDS.get(initial)
        or _DIACRITIC_SOUNDS.get(re.sub(_VOWELS, "", initial))
    )

def _is_invalid_romaji(romaji: str) -> bool:
    # If any part of a chord is left untranslated from the original chord,
    # (i.e. still in uppercase) consider it an invalid stroke for romaji output.
    return any(character.isupper() for character in romaji)
