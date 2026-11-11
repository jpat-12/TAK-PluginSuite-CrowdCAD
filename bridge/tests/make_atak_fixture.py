"""Regenerate atak/app/src/test/resources/bridge-demo.cot: the CoT this bridge sends for the
demo fixture, one event per line. The ATAK plugin's JVM tests parse it, so a wire-format change
on either side fails a test instead of a game day.

    cd bridge && python -m tests.make_atak_fixture        (or: python tests/make_atak_fixture.py)
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]

from crowdcad_tak import config  # noqa: E402
from crowdcad_tak.bridge import Publisher  # noqa: E402
from test_mapping import demo  # noqa: E402

OUT = os.path.join(HERE, "..", "..", "atak", "app", "src", "test", "resources", "bridge-demo.cot")
NOW = 1794701000000   # fixed, so the file only changes when the format does


def main():
    sent = []
    publisher = Publisher({**config.DEFAULTS, "team_uids": {"Team 2": "ANDROID-team2"}}, sent.append, lambda: NOW)
    publisher.apply(demo())
    event = demo()
    event["calls"][1]["status"] = "Refusal"      # one closed incident, as the bridge sends it
    publisher.apply(event)
    with open(OUT, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(sent) + "\n")
    print(f"wrote {len(sent)} events -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
