"""Fields shared by responses for user-owned model objects."""

from ninja import Schema


class OwnedObjectSchema(Schema):
    created_by_id: str
    created_by_username: str

    @staticmethod
    def resolve_created_by_id(obj):
        return str(obj.created_by.pk)

    @staticmethod
    def resolve_created_by_username(obj) -> str:
        user = obj.created_by
        return user.username if isinstance(user.username, str) else str(user)
