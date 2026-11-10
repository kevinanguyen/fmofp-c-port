"""The key of an AVN_CMD (ICD v1.20): up to 24 ASCII characters in twelve words, two per word, the
first in the high byte, padded with zeros. FORCE_FAULT and CLEAR_FAULT name a line replaceable unit
by it, as LRUStatusMonitor.force_fault(key) and clear_forced_fault(key) took a string (an LRU id, a
system key, or part of a name; a key that names no LRU declares one).

    m.AvnCmd(cmd_seq=1, command=AvionicsCommand.FORCE_FAULT, health=LruHealth.FAULT, **key_fields("gcas"))
"""

KEY_WORDS = 12
KEY_CHARS = 2 * KEY_WORDS


def key_fields(key):
    """key_0 ... key_11 for m.AvnCmd(**key_fields(key)); the key is cut to 24 characters, and a character
    outside printable ASCII becomes '?'."""
    codes = [ord(c) if 0x20 <= ord(c) <= 0x7E else ord("?") for c in str(key)[:KEY_CHARS]]
    codes += [0] * (KEY_CHARS - len(codes))
    return {f"key_{i}": (codes[2 * i] << 8) | codes[2 * i + 1] for i in range(KEY_WORDS)}


def key_text(command):
    """The key an AVN_CMD carries, up to its first zero character."""
    text = []
    for i in range(KEY_WORDS):
        word = getattr(command, f"key_{i}")
        for code in (word >> 8, word & 0xFF):
            if code == 0:
                return "".join(text)
            text.append(chr(code))
    return "".join(text)
