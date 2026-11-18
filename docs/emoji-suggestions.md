# Emoji suggestions

The keyboard offers one or two emoji for a common word, as the iOS keyboard does: "good" and
"好" offer 👍. This page describes the table of words and emoji, and where the emoji show.

## Where the emoji show

The candidate row is the row of words that lies over the prediction strip while it shows.
Select All, Cut, Copy and Paste stay in view beside it. The prediction strip is the part of the top
row between Select All and Cut, and [prediction-strip.md](prediction-strip.md) describes it.

- **English:** when the word right before the cursor is in the table, its emoji take the first
  places of the prediction strip. The word is the word the person is typing, or the word
  before one space. The predicted words follow the emoji. The emoji take no row of their own.
  - The keys of the top row keep their place and their size when emoji come and go.
  - A tap on an emoji types that emoji. The emoji takes touches over the full height of the
    row and up to the keyboard's upper edge. Every other touch on the row reaches its key, and
    the row reacts at once after the emoji leave.
  - A tap puts the emoji in place of the word, as the iOS keyboard does: "good " and a tap on
    👍 give "👍 ". The space after the word stays. One delete right after the tap brings the
    word back, as one delete after an autocorrection does, and the word stays open to later
    corrections. The tap runs no autocorrection, and typing keeps its autocorrection.
  - While the proofreader's fix shows, the candidate row covers the prediction strip, so the
    row shows the emoji after the fix.
- **Chinese:** when the first Pinyin candidate is a word in the table, its emoji come right
  after that candidate. A tap types the emoji in place of the word, and the emoji takes the
  Pinyin letters of the word. The space bar and the digit keys still pick the Pinyin
  candidates in their own order.
- A field without autocorrection gets no emoji. The keyboard reads such a field from the
  field's settings, as for autocorrection: an address, an email or a number field, or a field
  that turns autocorrection off. iOS does not show a third-party keyboard in a password field.
- An emoji is not a mark, so it takes no space removal. A mark after the emoji and one space
  keeps that space.

## The table

`Shared/emoji-suggestions.tsv` holds 328 English words with 263 different emoji, and 264
Chinese words with 263 different emoji. Each word has one or two emoji.

| Language | Examples |
| --- | --- |
| English | good 👍 👏, love ❤️ 😍, happy 😁 😄, lol 😂 🤣, thanks 🙏, party 🎉 🎊, birthday 🎂 🎉, coffee ☕, dog 🐶 🐕, fire 🔥 |
| Chinese | 好 👍, 哈哈 🤣 😆, 爱 ❤️ 😍, 谢谢 🙏, 你好 👋, 生日 🎂 🎉, 开心 😆 😄, 猫 🐱 🐈, 咖啡 ☕, 晚安 😴 💤 |

The words and their emoji are chosen by hand in `scripts/emoji-table/chosen-en.tsv` and
`scripts/emoji-table/chosen-zh.tsv`. The choice leaves out very frequent words such as
"like", "see" and "time", because their emoji would come and go at almost every word. The choice also leaves out words for groups of people.

`scripts/emoji-table/build_emoji_table.py` checks every chosen pair and writes the table:

1. The Unicode CLDR emoji annotations of the language must name the word for the emoji, as a
   keyword or as a word of the emoji's spoken name.
2. The emoji must be among the 700 most used emoji of the Unicode emoji frequency ranking.
3. An English word must be among the 30,000 most frequent words of SymSpell's word list. Four
   chat words that the list does not hold ("lol", "haha", "omg", "idk") are accepted by name.
   A Chinese word must be among the 10,000 most frequent words of
   `Shared/pinyin-dictionary.txt`.

The script downloads the sources into `build/emoji-table/` and stops when the SHA-256 of a
file differs from `scripts/emoji-table/source-hashes.json`.

Run it with:

```
python scripts/emoji-table/build_emoji_table.py
python scripts/emoji-table/build_emoji_table.py --candidates en good happy
```

The second form prints every emoji whose annotations name each word, most used first.

## Sources and licenses

| Source | Version | License |
| --- | --- | --- |
| [Unicode CLDR](https://cldr.unicode.org/) emoji annotations, files `annotations/en` and `annotations/zh` of the npm package `cldr-annotations-full` | 49.0.0 | [Unicode License v3](https://www.unicode.org/license.txt) |
| [Unicode emoji frequency](https://home.unicode.org/emoji/emoji-frequency/) | page of 2022 | [Unicode License v3](https://www.unicode.org/license.txt) |
| SymSpell `frequency_dictionary_en_82_765.txt` | master branch, hash in `source-hashes.json` | MIT |

The Unicode License v3 allows the use, copy and change of the data with the copyright notice.
The table file names the CLDR version and its license in its header lines.
