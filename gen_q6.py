import json
import tempfile

from tests.helpers import *  # noqa
from tests import test_guards_golden as t
from src.config import load_config

cfg = load_config()
got = t._q6_base_cmds(t._q6_cfg_off(cfg), tempfile.mkdtemp())
json.dump(got, open(t.Q6_BASE_FIXTURE, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print(len(got["v2"]), len(got["v1"]))
