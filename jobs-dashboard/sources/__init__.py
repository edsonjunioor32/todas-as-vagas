# -*- coding: utf-8 -*-
"""Registry of public, key-free job sources."""
from . import ats_boards, empregare, gupy, inhire, remote_boards, themuse, wwr

REGISTRY = [
    ("inhire", inhire.fetch),
    ("empregare", empregare.fetch),
    ("gupy", gupy.fetch),
    ("themuse", themuse.fetch),
    ("remotive", remote_boards.fetch_remotive),
    ("jobicy", remote_boards.fetch_jobicy),
    ("remoteok", remote_boards.fetch_remoteok),
    ("himalayas", remote_boards.fetch_himalayas),
    ("workingnomads", remote_boards.fetch_workingnomads),
    ("arbeitnow", remote_boards.fetch_arbeitnow),
    ("weworkremotely", wwr.fetch),
    ("greenhouse", ats_boards.fetch_greenhouse),
    ("lever", ats_boards.fetch_lever),
    ("ashby", ats_boards.fetch_ashby),
]
