"""Declarative command catalog shared by both matcher implementations."""

REBUILD_INDEX = "rebuild_index"

# Each command maps to a group of trigger phrases: literal substrings for the
# substring matcher, synonym embeddings for the semantic matcher. Declaration
# order is the disambiguation order when several commands could match.
COMMAND_CATALOG: dict[str, tuple[str, ...]] = {
    REBUILD_INDEX: (
        "重建索引",
        "重新建立索引",
        "重建文件索引",
        "rebuild index",
    ),
}
