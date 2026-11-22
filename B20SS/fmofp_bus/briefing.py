"""MSN_BRIEF_CMD's text on the bus (unit 37, ICD v1.29): two characters a word, the first in the high byte, 0 padding."""

from fmofp_bus.icd import messages as m

TEXT_WORDS = 12
KEY_WORDS = 4


def pack(text, words):
    """The words of up to 2 x words characters (ASCII; others become '?')."""
    data = text.encode("ascii", "replace")[:2 * words].ljust(2 * words, b"\0")
    return [(data[2 * i] << 8) | data[2 * i + 1] for i in range(words)]


def unpack(values):
    out = []
    for word in values:
        for code in ((word >> 8) & 0xFF, word & 0xFF):
            if code == 0:
                return "".join(out)
            out.append(chr(code))
    return "".join(out)


def brief_command(command, text="", key="", cmd_seq=0):
    """An MSN_BRIEF_CMD: the text in text_0..text_11, an intelligence key in key_0..key_3."""
    fields = {f"text_{i}": w for i, w in enumerate(pack(text, TEXT_WORDS))}
    fields.update({f"key_{i}": w for i, w in enumerate(pack(key, KEY_WORDS))})
    return m.MsnBriefCmd(command=command, cmd_seq=cmd_seq, **fields)


def text_of(message):
    return unpack([getattr(message, f"text_{i}") for i in range(TEXT_WORDS)])


def key_of(message):
    return unpack([getattr(message, f"key_{i}") for i in range(KEY_WORDS)])
