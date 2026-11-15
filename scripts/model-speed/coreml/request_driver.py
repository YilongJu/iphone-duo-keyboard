"""Turns the requests of the speed test into calls of the scoring model of scoring_model.py.

The rules copy LanguageModel/duo_lm_scorer.c with the keyboard's reuse mode, the anchored window
with two slots (DUO_LM_REUSE_ANCHOR, 2 slots), so a request reads the same window as in the
keyboard. Shared/CoreMLScorer.swift follows the same rules on the phone.

Each request makes two calls of the model:
  window call     the tokens of the window after the ones the slot's cache keeps
  candidate call  every token of every candidate in one call. Each candidate attends to the
                  window and to its own earlier tokens only, through the attention mask.

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


# A call of the model: (state, input_ids, position_ids, attention_mask, target_ids) gives
# (last_logits [V], target_logit [Q], log_norm [Q], space_log_mass [Q]) as numpy arrays.
ModelCall = Callable[[object, np.ndarray, np.ndarray, np.ndarray, np.ndarray], tuple]


class Driver:
    def __init__(self, call: ModelCall, make_state: Callable[[], object]):
        self.call = call
        self.slots = [Slot(state=make_state()) for _ in range(SLOTS)]
        self.requests = 0
        self.window_tokens = 0
        self.window_tokens_reused = 0
        self.tokens_read = 0

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

        # The window call: the unread tokens at their positions, each attending to every cell
        # up to its own.
        unread = count - kept
        mask = np.full((1, 1, unread, count), MASKED, dtype=np.float16)
        for row in range(unread):
            mask[0, 0, row, : kept + row + 1] = 0
        ids = np.array([window[kept:]], dtype=np.int32)
        positions = np.arange(kept, count, dtype=np.int32)[None, :]
        last_logits, _, window_norm, _ = self.call(slot.state, ids, positions, mask, np.zeros_like(ids))
        after_window = float(window_norm[-1])

        # The candidate call: every candidate after the window, each in cells of its own.
        tokens, targets, places, owners = [], [], [], []
        for owner, candidate in enumerate(request.candidates):
            for place, token in enumerate(candidate):
                tokens.append(token)
                targets.append(candidate[place + 1] if place + 1 < len(candidate) else 0)
                places.append(place)
                owners.append(owner)
        total = len(tokens)
        mask = np.full((1, 1, total, count + total), MASKED, dtype=np.float16)
        mask[0, 0, :, :count] = 0
        first_row = {}
        for row in range(total):
            first_row.setdefault(owners[row], row)
            begin = count + first_row[owners[row]]
            mask[0, 0, row, begin : count + row + 1] = 0
        ids = np.array([tokens], dtype=np.int32)
        positions = np.array([[count + place for place in places]], dtype=np.int32)
        _, target_logit, log_norm, space_log_mass = self.call(
            slot.state, ids, positions, mask, np.array([targets], dtype=np.int32))
        scores = []
        for owner, candidate in enumerate(request.candidates):
            log_probability = float(last_logits[candidate[0]]) - after_window
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
