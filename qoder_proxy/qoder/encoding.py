import base64

CUSTOM_ALPHABET = "_doRTgHZBKcGVjlvpC,@aFSx#DPuNJme&i*MzLOEn)sUrthbf%Y^w.(kIQyXqWA!"
STD_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
CUSTOM_PAD = "$"

_TO_CUSTOM = str.maketrans(STD_ALPHABET + "=", CUSTOM_ALPHABET + CUSTOM_PAD)
_TO_STD = str.maketrans(CUSTOM_ALPHABET + CUSTOM_PAD, STD_ALPHABET + "=")


def encode(plaintext: bytes) -> str:
    standard = base64.b64encode(plaintext).decode("ascii")
    n = len(standard)
    pivot = n // 3
    rearranged = standard[n - pivot :] + standard[pivot : n - pivot] + standard[:pivot]
    return rearranged.translate(_TO_CUSTOM)


def decode(encoded: str) -> bytes:
    mapped = encoded.translate(_TO_STD)
    n = len(mapped)
    pivot = n // 3
    standard = mapped[n - pivot :] + mapped[pivot : n - pivot] + mapped[:pivot]
    return base64.b64decode(standard)
