"""The progress text an OCR node publishes while it waits on its provider."""


def cached_progress(message: str, hits: list[bool]) -> str:
    """The step's message, with how many of its provider calls the cache answered.

    Both OCR nodes work in windows or crops, so one node computation is many
    provider calls and a rerun over the same pixels can make none of them. Without
    the count, a run that spent no provider time at all is indistinguishable on the
    card from one that has not got there yet.
    """

    cached = sum(hits)
    if cached == 0:
        return message
    return f"{message} · {cached} cached"
