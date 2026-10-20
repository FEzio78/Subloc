"""Errors with a message an ordinary user can act on. `str(e)` is that message; `detail` is for logs."""


class SublocError(Exception):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


class TranslatorUnavailable(SublocError):
    """The LLM server can't be reached (closed, server not started, wrong address). Stop the job;
    progress is saved and Start resumes."""


class ModelNotAvailable(SublocError):
    pass


class ContextTooLong(SublocError):
    """The request didn't fit the model's context window: send fewer lines at once."""


class MediaError(SublocError):
    pass


def friendly_os_error(e: OSError, what: str) -> SublocError:
    import errno

    if e.errno == errno.ENOSPC:
        return SublocError(f"The disk is full — couldn't save {what}. Free some space and press Start again.", str(e))
    if e.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return SublocError(
            f"Windows didn't allow saving {what} in this folder. "
            f"Move the video to a folder you can write to (e.g. Videos or Desktop).",
            str(e),
        )
    return SublocError(f"Couldn't save {what}: {e.strerror or e}", str(e))
