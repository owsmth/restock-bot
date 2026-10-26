from __future__ import annotations


class ServiceError(Exception):
    """Base error with a message that is safe to show to a Discord user."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class StoreNotFoundError(ServiceError):
    def __init__(self, store_id: int) -> None:
        super().__init__(f"Store {store_id} was not found.")


class StoreInactiveError(ServiceError):
    def __init__(self, store_name: str) -> None:
        super().__init__(f"{store_name} is not currently accepting reports.")


class DuplicateReportError(ServiceError):
    def __init__(self) -> None:
        super().__init__(
            "You already submitted that exact report in the last 30 minutes. "
            "If conditions changed, update the in-stock value or try again later."
        )


class InvalidReportError(ServiceError):
    pass


class ReportingUnavailableError(ServiceError):
    def __init__(self) -> None:
        super().__init__(
            "Reporting is temporarily unavailable because the report source "
            "is not configured. Please contact a server operator."
        )


class RateLimitExceededError(ServiceError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            f"You reached the limit of {limit} reports per hour. Please wait a while and try again."
        )


class ReportNotFoundError(ServiceError):
    def __init__(self, observation_id: int) -> None:
        super().__init__(f"Report {observation_id} was not found.")
