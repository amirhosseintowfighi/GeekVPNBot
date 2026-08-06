"""Row <-> aggregate translation.

Kept out of the repositories so that both directions of every mapping sit next
to each other. A `to_domain` that drifts from its `to_row` is the classic way a
field silently stops being persisted, and the only reliable defence is making
the pair impossible to read separately.
"""
