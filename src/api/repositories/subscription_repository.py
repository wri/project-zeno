from src.api.services.subscription import (
    Subscription,
    SubscriptionRepository,
)


class EmptySubscriptionRepository(SubscriptionRepository):
    """Placeholder until subscriptions are persisted."""

    async def list_active(self) -> list[Subscription]:
        return []


def get_subscription_repository() -> SubscriptionRepository:
    return EmptySubscriptionRepository()
