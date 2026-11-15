"""Reads the rows of one table from a MySQL dump, as lists of Python values.

The Aalto typing studies publish their data as MySQL dumps. This module streams such a dump line
by line and parses the INSERT statements of the named tables only, so a dump of several
gigabytes does not need a database server or much memory.
"""
from typing import Iterable, Iterator

ESCAPES = {"0": "\0", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a", "b": "\b"}


def parse_values(text: str, start: int) -> Iterator[list]:
    """The tuples of a VALUES list that starts at `start`: "(1,'a',NULL),(2,'b',3.5);"."""
    index = start
    length = len(text)
    while index < length:
        character = text[index]
        if character in " \t\r\n,":
            index += 1
            continue
        if character == ";":
            return
        if character != "(":
            raise ValueError(f"expected a tuple at {index}: {text[index:index + 40]!r}")
        index += 1
        row = []
        while True:
            while text[index] in " \t\r\n":
                index += 1
            character = text[index]
            if character == "'":
                index += 1
                parts = []
                while True:
                    end = index
                    while text[end] not in "'\\":
                        end += 1
                    parts.append(text[index:end])
                    if text[end] == "\\":
                        escaped = text[end + 1]
                        parts.append(ESCAPES.get(escaped, escaped))
                        index = end + 2
                        continue
                    if text[end + 1:end + 2] == "'":
                        parts.append("'")
                        index = end + 2
                        continue
                    index = end + 1
                    break
                row.append("".join(parts))
            else:
                end = index
                while text[end] not in ",)":
                    end += 1
                token = text[index:end].strip()
                if token == "NULL":
                    row.append(None)
                else:
                    try:
                        row.append(int(token))
                    except ValueError:
                        row.append(float(token))
                index = end
            while text[index] in " \t\r\n":
                index += 1
            if text[index] == ",":
                index += 1
                continue
            if text[index] == ")":
                index += 1
                break
            raise ValueError(f"unexpected {text[index]!r} at {index}")
        yield row


def table_rows(lines: Iterable[str], table: str) -> Iterator[list]:
    """Every row of `table` in a dump. A statement may name its columns, and it may put VALUES on
    the next lines, as the dump of Sequel Pro does."""
    prefix = f"INSERT INTO `{table}`"
    pending = None
    for line in lines:
        if pending is not None:
            pending.append(line)
            if line.rstrip().endswith(";"):
                text = "".join(pending)
                pending = None
                yield from parse_values(text, text.index("VALUES") + len("VALUES"))
            continue
        if not line.startswith(prefix):
            continue
        if line.rstrip().endswith(";"):
            yield from parse_values(line, line.index("VALUES") + len("VALUES"))
        else:
            pending = [line]
