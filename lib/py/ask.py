"""Reading one account by launching it, and saying so while it happens.

The one way an account gets asked what it has left. Rotation asks before it switches, reads
ahead when a switch is close, and `ccex use` asks the account you named -- three callers that
were writing three sets of lines for the same event. This is the event: the trail says the
same thing whether a timer started it or you pressed a key.
"""
from ccexlib import REFUSED, step
from decide import reads
from probe import probe
from usage import account_json


def ask(name, d, was=None, miss="", refused=None):
    """Launch this account, read its own numbers, and hand back (status, its row).

    `was` is what was on file, said up front so a reading that disagrees is visible. `miss`
    is what the caller does about a failure, said on the same line as the failure -- the trail
    is read a line at a time and "it did not answer" without "so I am doing X" reads as a stop.

    A refusal gets its own line, and `refused` its own words where the caller does something
    different about it: an account whose organisation has turned Claude Code off did answer,
    and what a caller does about being told no is rarely what it does about silence.

    The row is re-read here rather than by the caller: all three of them wanted exactly the
    same thing, which is what the account looks like now that it has answered.
    """
    step("asking %s%s" % (name, "" if was is None else " (on file: %s)" % was))
    st = probe(d)
    if st in REFUSED:
        step("%s says no (%s)%s" % (name, st, miss if refused is None else refused))
        return st, None
    if st != "ok":
        step("%s did not answer (%s)%s" % (name, st, miss))
        return st, None
    row = account_json(name, d)
    step("%s answered %s" % (name, reads(row)))
    return st, row
