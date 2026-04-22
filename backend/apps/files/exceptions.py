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
