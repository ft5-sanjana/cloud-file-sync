class FileValidationError(Exception):
    """User-facing file validation failure (bad extension, MIME, etc)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FileTooLargeError(FileValidationError):
    def __init__(self, max_bytes: int) -> None:
        super().__init__(
            "FILE_TOO_LARGE",
            f"File exceeds maximum size of {max_bytes} bytes.",
        )


class UnsupportedFileTypeError(FileValidationError):
    def __init__(self, extension: str) -> None:
        super().__init__(
            "UNSUPPORTED_TYPE",
            f"Files with extension '.{extension}' are not allowed.",
        )


class MimeMismatchError(FileValidationError):
    def __init__(self, extension: str, sniffed: str) -> None:
        super().__init__(
            "MIME_MISMATCH",
            f"File extension '.{extension}' does not match detected content type '{sniffed}'.",
        )


class FileBusyError(Exception):
    """Raised when a file can't be modified right now (e.g. a DELETE arrives
    while the upload is still streaming). The client should retry in a
    moment once the in-flight operation settles. Maps to HTTP 409.
    """

    def __init__(self, message: str = "File is busy, please retry in a moment.") -> None:
        super().__init__(message)
        self.code = "FILE_BUSY"
        self.message = message


class FolderNameInvalidError(FileValidationError):
    """Folder name or relative path failed validation."""

    def __init__(self, message: str) -> None:
        super().__init__("FOLDER_NAME_INVALID", message)


class FolderNotFoundError(Exception):
    """Folder doesn't exist or isn't owned by the caller.

    Mapped to 404 at the API boundary. Deliberately the same status as
    "no such folder" to avoid leaking cross-user folder existence.
    """

    def __init__(self, message: str = "Folder not found.") -> None:
        super().__init__(message)
        self.code = "FOLDER_NOT_FOUND"
        self.message = message


class FolderConflictError(Exception):
    """Sibling name collision — attempted to create a folder whose name
    already exists under the same parent (or at root).

    Maps to HTTP 409. The DB partial-unique constraints are the
    source-of-truth; this exception is what surfaces that violation to
    the user without dumping a Postgres error.
    """

    def __init__(
        self, message: str = "A folder with this name already exists here."
    ) -> None:
        super().__init__(message)
        self.code = "FOLDER_CONFLICT"
        self.message = message


class FolderTooLargeError(Exception):
    """Folder subtree exceeds the synchronous-delete/zip cap.

    We process delete + ZIP synchronously so the user sees a real
    success before we return — that requires bounding the workload. A
    subtree bigger than the cap needs a background-task flow we don't
    ship in the MVP. Maps to HTTP 413.
    """

    def __init__(self, count: int, cap: int) -> None:
        super().__init__("Folder is too large for this operation.")
        self.code = "FOLDER_TOO_LARGE"
        self.count = count
        self.cap = cap
        self.message = (
            f"Folder contains {count} files, which exceeds the limit of "
            f"{cap} for this operation."
        )


class QuotaExceededError(Exception):
    def __init__(self, used: int, quota: int, incoming: int) -> None:
        super().__init__("Storage quota exceeded.")
        self.code = "QUOTA_EXCEEDED"
        self.used = used
        self.quota = quota
        self.incoming = incoming
        self.message = (
            f"Storage quota exceeded "
            f"({used + incoming} would exceed limit of {quota})."
        )
