"""The toneless Pinyin of a Chinese clause, for the Pinyin cases of the typo set, or None when
the reading of one character is not certain.

pypinyin alone picks wrong readings in two ways:
1. It cuts the clause with its own phrase list, and a phrase can cross a word boundary. "我的哥哥"
   holds the phrase "的哥" (di ge, taxi driver), so pypinyin reads "wo di ge ge". "证明了" holds
   "明了" (ming liao).
2. A character outside a phrase gets its first reading, as "di" for the adverb ending 地 and
   "zhang" for 长 in "很长".

So this module cuts the clause into words with jieba first (MIT licence,
https://github.com/fxsjy/jieba), with its hidden Markov model off, so that the cut depends on the
word list alone. A word of two characters or more that pypinyin's phrase list holds gets the
phrase reading. pypinyin cuts any other word with its own phrase list, inside the word only. A
character that stands outside every phrase of the list gets its one reading, with two kinds of
exception:
- A character of `UNCERTAIN` has two readings that both occur outside phrases, as 地 (de, di),
  得 (de, dei), 还 (hai, huan) and 长 (chang, zhang). A clause with such a character outside a
  phrase gets no reading, and the builders leave it out.
- A word of `UNCERTAIN_WORDS` has two common readings as a whole, as 同行 (tong xing, go
  together, and tong hang, people of one trade), or the cut can be wrong, as 目的地 (mu di di,
  destination) in "毫无目的地" (hao wu mu di de), or pypinyin's phrase list gives it a wrong
  reading. A clause with such a word gets no reading.

pypinyin lists rare readings for many common characters, as "ti" for 是 and "tuo" for 他. The
reading outside a phrase is pypinyin's first reading, which for these characters is the common
one. `UNCERTAIN` therefore names the characters whose second reading is common, and only them.
"""
import jieba
from pypinyin import Style, lazy_pinyin, pinyin
from pypinyin.constants import PHRASES_DICT
from pypinyin.seg.mmseg import seg

jieba.setLogLevel(60)

# Characters with two toneless readings that both occur outside a fixed phrase.
UNCERTAIN = set(
    "地得还着长行觉弹重便乐数差调传朝曾校角降似系参藏省落血奇卡区单恶盛露塞薄削剥色熟模解圈吓折埋宿称"
    "泊粘扎佛仔率伯柏夹咖屏俩尾蔓臭拓囤嚼哦")
# Words whose whole reading is not certain: two common readings, or a wrong entry in pypinyin's
# phrase list.
UNCERTAIN_WORDS = {"同行", "犯得上", "目的地"}


class Reader:
    def __init__(self):
        single = sorted(c for c in UNCERTAIN if len({r for r in pinyin(c, style=Style.NORMAL, heteronym=True)[0]}) < 2)
        if single:
            raise SystemExit(f"these characters of UNCERTAIN have one toneless reading only: {''.join(single)}")
        self.cache: dict[str, list[str] | None] = {}
        self.uncertain_clauses = 0

    def syllables(self, clause: str) -> list[str] | None:
        if clause in self.cache:
            return self.cache[clause]
        out: list[str] | None = []
        for word in jieba.lcut(clause, HMM=False):
            if word in UNCERTAIN_WORDS:
                out = None
                break
            if len(word) > 1 and word in PHRASES_DICT:
                out += lazy_pinyin(word, style=Style.NORMAL)
                continue
            for piece in seg.cut(word):
                if piece in UNCERTAIN_WORDS:
                    out = None
                    break
                if len(piece) > 1 and piece in PHRASES_DICT:
                    out += lazy_pinyin(piece, style=Style.NORMAL)
                    continue
                if any(character in UNCERTAIN for character in piece):
                    out = None
                    break
                out += lazy_pinyin(piece, style=Style.NORMAL)
            if out is None:
                break
        if out is not None and len(out) != len(clause):
            out = None
        if out is None:
            self.uncertain_clauses += 1
        self.cache[clause] = out
        return out
