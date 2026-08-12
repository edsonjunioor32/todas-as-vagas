def iso_date(value):
    """Normalize a portal date while preserving a supplied publication time.

    Date-only values remain YYYY-MM-DD. ISO adapters that pass an hour keep an
    ISO-8601 timestamp so the public page can show it.
    """
    if value is None or value == "":
        return ""

    try:
        seconds = int(value)
        if seconds > 10_000_000:  # plausibly a unix timestamp, not a year
            if seconds > 10_000_000_000:  # milliseconds
                seconds /= 1000
            return datetime.fromtimestamp(
                seconds, tz=timezone.utc
            ).isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError, OSError):
        pass

    text = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:T|\s)\d{2}:\d{2}", text):
        try:
            return datetime.fromisoformat(
                text.replace("Z", "+00:00")
            ).isoformat(timespec="seconds")
        except ValueError:
            pass

    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else ""
