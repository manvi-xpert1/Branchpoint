"""Service-level errors. The API layer maps them to HTTP status codes."""


class ServiceError(Exception):
    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409


class InvalidInput(ServiceError):
    status_code = 422
