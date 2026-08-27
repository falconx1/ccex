"""Reading one account by launching it, and saying so while it happens.

The one way an account gets asked what it has left. Rotation asks before it switches, reads
ahead when a switch is close, and `ccex use` asks the account you named -- three callers that
were writing three sets of lines for the same event. This is the event: the trail says the
same thing whether a timer started it or you pressed a key.
"""
from ccexlib import reads, step
from probe import probe


def ask(name, d, was=None, after=None, miss=""):
    """Launch this account, read its own numbers, return the probe status.

    `was` is what was on file, said up front so a reading that disagrees is visible. `after`
    refreshes the caller's row once it answered, so the line can say what came back. `miss`
    is what the caller does about a failure, said on the same line as the failure -- the trail
    is read a line at a time and "it did not answer" without "so I am doing X" reads as a stop.
    """
    step("asking %s%s" % (name, "" if was is None else " (on file: %s)" % was))
    st = probe(d)
    if st != "ok":
        step("%s did not answer (%s)%s" % (name, st, miss))
        return st, None
    row = after() if after else None
    step("%s answered%s" % (name, " " + reads(row) if row else ""))
    return st, row
