"""Local search on one line: best improvement over three moves until none helps.

- **replace**: a station by an unused candidate;
- **swap**: two stations trade places;
- **move**: a station to another place in the line.

The colonies apply it to the iteration-best line before the pheromone update
(``optimize.local_search``), as MMAS does in Stützle & Hoos (2000): the ants find the region,
the local search the bottom of it. Random search polishes its iteration best the same way
(multi-start local search) and greedy its final line, so the comparison is fair. Every line
it tries counts as an evaluation.
"""

from __future__ import annotations

from .objective import Objective


def neighbours(line: list[int], n: int) -> list[list[int]]:
    k = len(line)
    used = set(line)
    out = [line[:i] + [c] + line[i + 1 :] for i in range(k) for c in range(n) if c not in used]
    for i in range(k):
        for j in range(i + 1, k):
            s = list(line)
            s[i], s[j] = s[j], s[i]
            out.append(s)
    for i in range(k):
        rest = line[:i] + line[i + 1 :]
        out += [rest[:j] + [line[i]] + rest[j:] for j in range(k) if j != i]
    return out


def improve(f: Objective, line: list[int], cost: float, n: int) -> tuple[list[int], float]:
    """Best-improvement descent from ``line`` (of cost ``cost``) to a local optimum, or
    until the objective's evaluation budget is spent."""
    while not f.spent:
        best, best_cost = None, cost
        for c in neighbours(line, n):
            if f.spent:  # mid-neighbourhood: take the best move seen so far, then stop
                break
            cc = f(c)
            if cc < best_cost:
                best, best_cost = c, cc
        if best is None:
            break
        line, cost = best, best_cost
    return line, cost
