"""Turns the requests of the speed test into calls of the scoring model of scoring_model.py.

The rules copy LanguageModel/duo_lm_scorer.c with the keyboard's reuse mode, the anchored window
with two slots (DUO_LM_REUSE_ANCHOR, 2 slots), so a request reads the same window as in the
keyboard. Shared/CoreMLScorer.swift follows the same rules on the phone.

Each request makes two calls of the flexible form of the model:
  window call     the tokens of the window after the ones the slot's cache keeps. Only its last
                  token is scored.
  candidate call  every token of every candidate in one call. Each candidate attends to the
                  window and to its own earlier tokens only, through the attention mask.
The fixed form pads each call to the smallest of its sizes that holds the tokens, and splits a
part that is longer than its largest size into several calls.

The tokens come from `speed_cli tokens` (scripts/model-speed/speed_cli.c), so every runtime
reads the tokens of llama.cpp's tokenizer.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Callable

import numpy as np

MAX_CONTEXT_TOKENS = 96
ANCHOR_REFILL_TOKENS = 64
MIN_UNREAD_TOKENS = 2
SLOTS = 2
MASKED = -30000.0
# CACHE_CELLS and FIRST_TOKENS of scoring_model.py.
CACHE_CELLS = 512
FIRST_TOKENS = 8


@dataclasses.dataclass
class Request:
    start: int
    context: list[int]
    candidates: list[list[int]]


def read_tokens(path: pathlib.Path) -> list[Request]:
    requests = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("\t")
        numbers = [[int(token) for token in field.split()] for field in fields]
        requests.append(Request(start=numbers[0][0], context=numbers[1], candidates=numbers[2:]))
    return requests


@dataclasses.dataclass
class Slot:
    tokens: list[int] = dataclasses.field(default_factory=list)
    count: int = 0
    window_start: int = 0
    context: list[int] = dataclasses.field(default_factory=list)
    last_use: int = 0
    state: object = None


def shared_start(first: list[int], second: list[int]) -> int:
    length = 0
    while length < len(first) and length < len(second) and first[length] == second[length]:
        length += 1
    return length


def plan_for_slot(slot: Slot, context: list[int]) -> tuple[int, int]:
    """The window start and the kept tokens of a request with this slot (plan_for_slot of C)."""
    count = len(context)
    window_start = count - MAX_CONTEXT_TOKENS if count > MAX_CONTEXT_TOKENS else 0
    if count > MAX_CONTEXT_TOKENS:
        anchor = slot.window_start
        same = shared_start(slot.context, context)
        keeps = slot.count > 0 and same > anchor and count - anchor <= MAX_CONTEXT_TOKENS
        window_start = anchor if keeps else count - ANCHOR_REFILL_TOKENS
    if slot.count == 0:
        return window_start, 0
    window = context[window_start:]
    return window_start, 1 + shared_start(slot.tokens[1 : slot.count], window)


# A call of the model: (state, inputs) gives (target_logit [R], log_norm [R], space_log_mass [R],
# first_logit [F]) as numpy arrays. `inputs` maps the input names of scoring_model.py to arrays.
ModelCall = Callable[[object, dict], tuple]


@dataclasses.dataclass
class Row:
    """One token of a call: its id, position, cell, the cells it attends to, and its target when
    the call scores it."""
    token: int
    position: int
    cell: int
    allowed: list[tuple[int, int]]
    target: int | None


class Driver:
    """`sizes` is None for the flexible form of scoring_model.py. For the fixed form it holds the
    token counts Q of its shapes, from small to large: a call takes the smallest size that holds
    its tokens, and a part longer than the largest size goes in several calls."""

    def __init__(self, call: ModelCall, make_state: Callable[[], object], sizes: list[int] | None = None):
        self.call = call
        self.sizes = sizes
        self.slots = [Slot(state=make_state()) for _ in range(SLOTS)]
        self.requests = 0
        self.window_tokens = 0
        self.window_tokens_reused = 0
        self.tokens_read = 0
        # The calls of the last request: (part, tokens of the call, padded size).
        self.calls: list[tuple[str, int, int]] = []

    def run(self, state, rows: list[Row], first_ids: list[int], scored_all: bool):
        """Reads `rows` in calls. With `scored_all` every row is scored; otherwise only the last row
        of the last call. Gives the outputs of each call, and the rows of each call."""
        if self.sizes is None:
            groups = [rows]
        else:
            largest = self.sizes[-1]
            groups = [rows[begin : begin + largest] for begin in range(0, len(rows), largest)]
        results = []
        first = np.zeros((1, FIRST_TOKENS), dtype=np.int32)
        first[0, : len(first_ids)] = first_ids
        for number, group in enumerate(groups):
            count = len(group)
            if self.sizes is None:
                size = count
                cells = max(row.cell for row in group) + 1
            else:
                size = next(size for size in self.sizes if size >= count)
                cells = CACHE_CELLS
            ids = np.zeros((1, size), dtype=np.int32)
            positions = np.zeros((1, size), dtype=np.int32)
            mask = np.full((1, 1, size, cells), MASKED, dtype=np.float16)
            write = np.zeros((1, size, cells), dtype=np.float16)
            for index, row in enumerate(group):
                ids[0, index] = row.token
                positions[0, index] = row.position
                for begin, end in row.allowed:
                    mask[0, 0, index, begin:end] = 0
                write[0, index, row.cell] = 1
            for index in range(count, size):
                # A padding row attends to cell 0 only, so its softmax has a finite sum.
                mask[0, 0, index, 0] = 0
            if scored_all:
                scored = list(range(size))
                targets = [row.target or 0 for row in group] + [0] * (size - count)
            else:
                scored = [count - 1]
                targets = [0]
            inputs = {
                "input_ids": ids, "position_ids": positions, "attention_mask": mask,
                "score_rows": np.array([scored], dtype=np.int32), "target_ids": np.array([targets], dtype=np.int32),
                "first_ids": first,
            }
            if self.sizes is not None:
                inputs["write_cells"] = write
            results.append((self.call(state, inputs), group))
            self.calls.append(("candidates" if scored_all else "window", count, size))
        return results

    def score(self, request: Request) -> list[tuple[float, float]]:
        self.requests += 1
        context = request.context
        plan = plan_for_slot(self.slots[0], context)
        other = plan_for_slot(self.slots[1], context)
        mine = plan[1] if plan[1] > 1 else 0
        theirs = other[1] if other[1] > 1 else 0
        if theirs > mine or (theirs == mine and mine == 0 and self.slots[1].last_use < self.slots[0].last_use):
            self.slots.reverse()
            plan = other
        slot = self.slots[0]
        window_start, kept = plan
        window = [request.start] + context[window_start:]
        count = len(window)
        kept = max(0, min(kept, count - MIN_UNREAD_TOKENS))

        self.calls = []
        # The window calls: the unread tokens at their positions and cells, each attending to
        # every cell up to its own. Only the last token is scored, with the first token of each
        # candidate as its first_ids.
        unread = count - kept
        rows = [Row(token=window[index], position=index, cell=index, allowed=[(0, index + 1)], target=None)
                for index in range(kept, count)]
        firsts = [candidate[0] for candidate in request.candidates]
        (_, window_norm, _, first_logit), _ = self.run(slot.state, rows, firsts, scored_all=False)[-1]
        after_window = float(window_norm[-1])

        # The candidate calls: every candidate after the window, each in cells of its own.
        rows, first_row = [], []
        for candidate in request.candidates:
            first_row.append(len(rows))
            for place, token in enumerate(candidate):
                cell = count + len(rows)
                rows.append(Row(token=token, position=count + place, cell=cell,
                                allowed=[(0, count), (count + first_row[-1], cell + 1)],
                                target=candidate[place + 1] if place + 1 < len(candidate) else 0))
        total = len(rows)
        target_logit, log_norm, space_log_mass = [], [], []
        for (target_part, norm_part, space_part, _), group in self.run(slot.state, rows, [], scored_all=True):
            target_logit += list(target_part[: len(group)])
            log_norm += list(norm_part[: len(group)])
            space_log_mass += list(space_part[: len(group)])
        scores = []
        for owner, candidate in enumerate(request.candidates):
            log_probability = float(first_logit[owner]) - after_window
            for place in range(len(candidate) - 1):
                row = first_row[owner] + place
                log_probability += float(target_logit[row]) - float(log_norm[row])
            last = first_row[owner] + len(candidate) - 1
            scores.append((log_probability, float(space_log_mass[last]) - float(log_norm[last])))

        self.window_tokens += count
        self.window_tokens_reused += kept
        self.tokens_read += unread + total
        slot.tokens = window
        slot.count = count if count > 1 else 0
        slot.window_start = window_start
        slot.last_use = self.requests
        slot.context = list(context)
        return scores
