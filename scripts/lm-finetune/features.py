"""The eight engine features of the linear listwise chooser (linear_features.py), and the scorer
that evaluate.py uses in place of a language model.

The features of a reading, against the typed span:
1. the engine score, 2. the slip cost, 3. the engine score less the slip cost,
4. 1 for the reading as typed, 5. 1 for the engine's choice,
6. the change in word count, 7. the change in length, 8. the edit distance (a swap of two
neighbors counts as one edit).
"""

NAMES = ["engine_score", "slip_cost", "lexicon_score", "as_typed", "chosen", "word_change", "length_change", "edits"]


def edits(first: str, second: str) -> int:
    table = [[0] * (len(second) + 1) for _ in range(len(first) + 1)]
    for i in range(len(first) + 1):
        table[i][0] = i
    for j in range(len(second) + 1):
        table[0][j] = j
    for i in range(1, len(first) + 1):
        for j in range(1, len(second) + 1):
            table[i][j] = min(table[i - 1][j] + 1, table[i][j - 1] + 1, table[i - 1][j - 1] + (first[i - 1] != second[j - 1]))
            if i > 1 and j > 1 and first[i - 1] == second[j - 2] and first[i - 2] == second[j - 1]:
                table[i][j] = min(table[i][j], table[i - 2][j - 2] + 1)
    return table[-1][-1]


def features(text: str, score: float, slips: float, as_typed: bool, chosen: bool, typed: str) -> list[float]:
    return [score, slips, score - slips, float(as_typed), float(chosen),
            float(len(text.split(" ")) - len(typed.split(" "))), float(len(text) - len(typed)), float(edits(typed, text))]


class FeatureScorer:
    """Gives each reading the score of the linear chooser, in the place of the model score.
    The space-after part is 0, so the space-after switch of a setting does not change it."""

    def __init__(self, weights: dict):
        if weights["names"] != NAMES:
            raise SystemExit("the weights file names other features")
        self.mean, self.scale, self.weights = weights["mean"], weights["scale"], weights["weights"]
        self.requests = 0
        self.cache: dict[tuple, dict[str, tuple[float, float]]] = {}

    def reading_scores(self, context: str, readings: list[dict], typed: str | None) -> dict[str, tuple[float, float]]:
        if typed is None:
            raise SystemExit("the feature scorer needs the typed span")
        # The features depend on the typed span and the readings only, not on the context.
        key = (typed, tuple((r["text"], r["score"], r["slips"], r["as_typed"], r["chosen"]) for r in readings))
        if key in self.cache:
            return self.cache[key]
        result = {}
        for reading in readings:
            values = features(reading["text"], reading["score"], reading["slips"], reading["as_typed"], reading["chosen"], typed)
            result[reading["text"]] = (sum(w * (v - m) / s for w, v, m, s in zip(self.weights, values, self.mean, self.scale)), 0.0)
        self.requests += 1
        self.cache[key] = result
        return result
