"""Exporter for knowledge graph topic hierarchy."""

from __future__ import annotations

from minerva.core.node import TopicNode
from minerva.kb.driver import Neo4jDriver


class Exporter:
    """Exporter for topic hierarchy and facts to markdown format."""

    def __init__(self, driver: Neo4jDriver):
        """
        Initialize exporter.

        Args:
            driver: Neo4j driver instance
        """
        self.driver: Neo4jDriver = driver

    async def get_root_topics(self) -> list[TopicNode]:
        """Get all root topics (topics with no parent)."""
        results: list[dict] = await self.driver.query(
            """
            MATCH (root:Topic)
            WHERE NOT (root)-[:IS_SUBTOPIC]->(:Topic)
            RETURN root
            ORDER BY root.level, root.name
            """
        )
        return [
            TopicNode(
                id=r["root"]["id"],
                name=r["root"]["name"],
                summary=r["root"]["summary"],
                summary_embedding=r["root"]["summary_embedding"],
                level=r["root"]["level"],
            )
            for r in results
        ]

    async def export_to_markdown(
        self, file_path: str, include_topic_summary: bool = False
    ) -> None:
        """
        Export topic hierarchy with facts to markdown format.

        Args:
            file_path: Path to output markdown file
            include_topic_summary: Whether to include topic summaries in the export
        """
        root_topics: list[TopicNode] = await self.get_root_topics()

        if not root_topics:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(
                    "# Topic Hierarchy\n\nNo topics found in the knowledge graph.\n"
                )
            return

        markdown_lines: list[str] = ["# Topic Hierarchy\n"]

        for root_topic in root_topics:
            topic_markdown: str = await self._format_topic_markdown(
                root_topic, include_summary=include_topic_summary
            )
            markdown_lines.append(topic_markdown)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(markdown_lines))

    async def _format_topic_markdown(
        self,
        topic: TopicNode,
        indent_level: int = 0,
        include_summary: bool = False,
    ) -> str:
        """
        Format a topic and its children as markdown.

        Args:
            topic: Topic node to format
            indent_level: Current indentation level (0 = root, 1 = first level, etc.)
            include_summary: Whether to include topic summaries

        Returns:
            Markdown string for the topic and its subtree
        """
        lines: list[str] = []

        if indent_level == 0:
            lines.append(f"\n## {topic.name}\n")
        else:
            # Use simpler indentation: just 2 spaces per level, max 3 levels
            indent: str = "  " * min(indent_level - 1, 3)
            lines.append(f"{indent}- **{topic.name}**\n")

        if include_summary and topic.summary:
            summary_indent: str = "  " * min(indent_level, 3) if indent_level > 0 else ""
            lines.append(f"{summary_indent}  {topic.summary}\n")

        if topic.level == 0:
            relations: list[dict] = await topic.get_relations(driver=self.driver)
            if relations:
                facts_indent: str = "  " * min(indent_level, 3) if indent_level > 0 else ""
                lines.append(f"\n{facts_indent}  *Facts:*\n")
                for rel in relations:
                    from_name: str = rel.get("from_name", "")
                    to_name: str = rel.get("to_name", "")
                    relation_type: str = rel.get("relation_type", "")
                    fact: str = rel.get("fact", "")
                    fact_indent: str = "  " * (min(indent_level, 3) + 1) if indent_level > 0 else ""
                    lines.append(
                        f"{fact_indent}  - **{from_name}** *{relation_type}* **{to_name}**: {fact}\n"
                    )
        else:
            children: list[TopicNode] = await topic.get_children(driver=self.driver)
            if children:
                for child in children:
                    child_markdown: str = await self._format_topic_markdown(
                        child, indent_level=indent_level + 1, include_summary=include_summary
                    )
                    lines.append(child_markdown)

        return "".join(lines)
