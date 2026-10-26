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
