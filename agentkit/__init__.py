import sys as _sys

# Τα Windows γράφουν στην κονσόλα με τοπική κωδικοσελίδα (cp1250/cp1253) και τα ελληνικά σπάνε τα print.
for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
