"""Deterministic identifier tokens and conservative English shadow stemming."""
from __future__ import annotations
import re
import unicodedata

STOPWORDS = set("a an and are as at be been being by can could did do does for from had has have how i if in into is it its may of on or our should so than that the their them then there these they this those to was we were what when where whether which who why will with without would you your implemented defined trace through including before after".split())
GENERIC = set("get set is has new init run value data default config error type".split())
WORD = re.compile(r"[^\W]+", re.UNICODE)


def split_identifier(value: str) -> list[str]:
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return [w.casefold() for w in re.findall(r"[^\W_]+", value)]


def words(text: str) -> list[str]:
    # Match FTS unicode61 accent folding without discarding non-Latin letters.
    text = text.casefold()
    if not text.isascii():
        text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return WORD.findall(text)


def stem(word: str) -> str:
    if len(word)<=3 or not word.isascii() or not word.isalpha():
        return word
    if word.endswith("ies") and len(word)>4:
        word=word[:-3]+"y"
    elif word.endswith("sses"):
        word=word[:-2]
    elif word.endswith("s") and not word.endswith(("ss","us","is")):
        word=word[:-1]
    for suffix in ("ing","ed"):
        if word.endswith(suffix) and len(word)>len(suffix)+2:
            word=word[:-len(suffix)]
            if len(word)>2 and word[-1]==word[-2] and word[-1] not in "aeiou":
                word=word[:-1]
            break
    for suffix,replacement in (("ization","ize"),("ational","ate"),("ation","ate"),("fulness","ful"),("ness",""),("ment","")):
        if word.endswith(suffix) and len(word)>len(suffix)+2:
            word=word[:-len(suffix)]+replacement
            break
    if word.endswith("e") and len(word)>3:
        word=word[:-1]
    return word


def analyze(text: str):
    original = list(dict.fromkeys(w for w in words(text) if w not in STOPWORDS))[:32]
    retained = set(original) | STOPWORDS
    secondary = list(dict.fromkeys(w for token in re.findall(r"[\w./:-]+", text) if set(words(token)) <= retained for w in split_identifier(token) if w not in STOPWORDS | GENERIC and w not in original))[:48]
    return original, secondary


def searchable_tokens(text: str) -> str:
    return " ".join(split_identifier(text))


def properties_shadow(text: str) -> str:
    """Unescape Java properties Unicode sequences without changing citations."""
    def unescape(match):
        slashes, digits = match.groups()
        return slashes[:-1] + chr(int(digits, 16)) if len(slashes) % 2 else match[0]
    text = re.sub(r"(\\+)u([0-9a-fA-F]{4})", unescape, text)
    # Join escaped UTF-16 surrogate pairs; malformed pairs become a non-word
    # replacement marker, never an invalid Unicode value in SQLite.
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
