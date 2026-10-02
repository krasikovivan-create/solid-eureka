"""BM25-поиск без внешних сервисов, с простым стеммингом для русского языка."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)

# Окончания, которые отрезаем (от длинных к коротким). Это упрощённый стеммер:
# он не идеален, но хорошо склеивает формы одного слова для поиска.
_RU_SUFFIXES = sorted(
    (
        "иями ями ами ием ией иях ого его ому ему ыми ими ая яя ое ее ые ие ый ий ой "
        "ую юю ом ем ам ям ах ях ов ев ей ия ие ию ии ть ться тся ет ют ут ит ат ят "
        "ешь ишь ем им ли ла ло ал ял ил ел а я о е ы и у ю ь й"
    ).split(),
    key=len,
    reverse=True,
)
_EN_SUFFIXES = ["ingly", "edly", "ing", "ies", "ed", "es", "ly", "s"]

STOPWORDS = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все",
    "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по",
    "только", "ее", "мне", "было", "вот", "от", "меня", "еще", "нет", "о", "из", "ему",
    "ли", "если", "уже", "или", "ни", "быть", "был", "до", "вас", "нибудь", "уж", "вам",
    "там", "потом", "себя", "ничего", "ей", "может", "они", "тут", "где", "есть", "надо",
    "ней", "для", "мы", "тебя", "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего",
    "раз", "тоже", "себе", "под", "будет", "ж", "тогда", "кто", "этот", "того", "потому",
    "этого", "какой", "ним", "здесь", "этом", "один", "почти", "мой", "тем", "чтобы",
    "нее", "были", "куда", "зачем", "всех", "можно", "при", "об", "это", "эти", "the",
    "a", "an", "of", "to", "in", "is", "and", "or", "for", "on", "with", "какие", "какая",
    "каком", "какую", "нам", "наш", "наша", "наши",
}  # fmt: skip


def stem(word: str) -> str:
    word = word.lower().replace("ё", "е")
    if word.isdigit() or len(word) <= 3:
        return word
    suffixes = _RU_SUFFIXES if re.search("[а-я]", word) else _EN_SUFFIXES
    for suf in suffixes:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            return word[: -len(suf)]
    return word


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in TOKEN_RE.findall(text or ""):
        low = raw.lower().replace("ё", "е")
        if low in STOPWORDS:
            continue
        tokens.append(stem(low))
    return tokens


@dataclass
class SearchHit:
    key: object
    score: float


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.keys: list[object] = []
        self.term_freqs: list[Counter[str]] = []
        self.lengths: list[int] = []
        self.doc_freq: Counter[str] = Counter()

    def add(self, key: object, text: str) -> None:
        tokens = tokenize(text)
        tf = Counter(tokens)
        self.keys.append(key)
        self.term_freqs.append(tf)
        self.lengths.append(len(tokens))
        self.doc_freq.update(tf.keys())

    def __len__(self) -> int:
        return len(self.keys)

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        terms = tokenize(query)
        if not terms or not self.keys:
            return []
        n = len(self.keys)
        avgdl = (sum(self.lengths) / n) or 1.0
        scores = [0.0] * n
        for term in set(terms):
            df = self.doc_freq.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, tf in enumerate(self.term_freqs):
                f = tf.get(term, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.lengths[i] / avgdl)
                scores[i] += idf * f * (self.k1 + 1) / denom
        ranked = sorted(
            (SearchHit(self.keys[i], s) for i, s in enumerate(scores) if s > 0),
            key=lambda h: h.score,
            reverse=True,
        )
        return ranked[:top_k]
