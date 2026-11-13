"""The withheld words of the domain round: one word of the pack in five gets no slip case in training.

build_domain_train_cases.py leaves these words out of its slip, twin and space cases. The
reports count the evaluation slips of these words apart, so they show what a model does for a
word of the pack whose slips it never trained on.
"""
import hashlib

WITHHELD_ONE_IN = 5


def number(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def is_withheld(term: str) -> bool:
    return number("lm-domain-term:" + term) % WITHHELD_ONE_IN == 0
