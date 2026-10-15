import os
import sys

for v in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_REF_NAME", "GITHUB_STEP_SUMMARY"):
    os.environ.pop(v, None)
from tests import helpers  # noqa: E402

helpers.install_fakes()
from tests import test_guards_golden as g  # noqa: E402

getattr(g, sys.argv[1])()
print("PASSED", len(helpers.PASSED), "FAILED", len(helpers.FAILED))
for f in helpers.FAILED:
    print(str(f)[:220])
