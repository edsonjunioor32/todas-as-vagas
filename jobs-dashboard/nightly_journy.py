# -*- coding: utf-8 -*-
"""Run only the Journy source for its dedicated overnight refresh."""
import os

# pipeline.selected_registry excludes night-only sources from the regular
# refresh. This explicit selector is the opt-in used by the nightly workflow.
os.environ["JOBS_SOURCES"] = "journy"

import pipeline  # noqa: E402


if __name__ == "__main__":
    pipeline.main()
