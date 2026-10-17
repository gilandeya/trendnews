import sys
import traceback

from tests import helpers
from tests import test_guards_golden, test_review, test_youtube

helpers.install_fakes()
name = sys.argv[1]
mod = {"golden": test_guards_golden, "review": test_review, "youtube": test_youtube}[name]
fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n))
       and getattr(getattr(mod, n), "__module__", "") == mod.__name__]
for fn in fns:
    try:
        fn()
    except Exception:
        helpers.FAILED.append(f"EXC {fn.__name__}")
        traceback.print_exc()
print("SUMMARY", name, "PASSED", len(helpers.PASSED), "FAILED", len(helpers.FAILED))
for f in helpers.FAILED:
    print("FAIL:", f)
