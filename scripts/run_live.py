"""The MVP interface: detection loop -> one-line debug console + logged event file.

Picks a CSISource (synthetic / replay / serial), runs preprocess -> features ->
detect -> state machine, and prints one line per confirmed alert:

    [10:15:22] ALERT - sudden collapse (confidence 0.91, stillness=24s)

Build no more UI than this until the gate passes.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("run_live script — the detection loop + one-line console.")


if __name__ == "__main__":
    main()
