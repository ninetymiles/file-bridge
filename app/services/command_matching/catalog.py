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
        # Consistency-check phrasings: the command verifies indexed records
        # against on-disk files and purges missing ones. Phrases must match
        # that verify/sync intent; "generate"-style phrases (生成索引) are
        # excluded because the command never scans disk to backfill files.
        "检查索引",
        "校验索引",
        "检查文件索引",
        "同步索引",
        "同步文件索引",
        "刷新索引",
        "刷新文件索引",
        "更新索引",
    ),
}
