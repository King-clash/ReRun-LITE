from . import tk_retry

tk_retry.install()   # a window start that fails to read Tk files by chance is retried (see tk_retry.py)
