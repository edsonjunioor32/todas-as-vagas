# -*- coding: utf-8 -*-
from pathlib import Path

PATH = Path("jobs-dashboard/sources/recrutei.py")
START = "def _needs_detail"
END = "\ndef _hydrate_cards"
REPLACEMENT = 'def _needs_detail(card):\n    publication = _relative_publication_date(card.get("publication"))\n    if publication:\n        try:\n            published_day = date.fromisoformat(publication)\n        except ValueError:\n            published_day = None\n        if published_day and published_day < date.today() - timedelta(days=70):\n            return False\n\n    location = str(card.get("location") or "").strip()\n    normalized = location.casefold()\n    model = _public_model(card.get("badges") or [])\n    # The public card is authoritative when Recrutei already exposes a work model.\n    # Do not open hundreds of details only to refine a generic Brasil location.\n    if model and normalized in {\n        "", "brasil", "brazil", "não informado", "nao informado"\n    }:\n        return False\n    return (\n        not location\n        or normalized in {"brasil", "brazil", "não informado", "nao informado"}\n        or bool(PUBLICATION_TIME.search(location))\n    )\n\n'

text = PATH.read_text(encoding="utf-8")
start = text.index(START)
end = text.index(END, start)
updated = text[:start] + REPLACEMENT + text[end:]
if updated != text:
    PATH.write_text(updated, encoding="utf-8")
    print("Recrutei detail optimization applied")
else:
    print("Recrutei detail optimization already applied")
