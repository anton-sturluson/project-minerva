"""MongoDB client for the Knowledge Base."""

from datetime import datetime
from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.results import UpdateResult, DeleteResult
from .model import Section
from .utils import generate_id, slugify, format_section_tree


class MongoKB:
    """MongoDB client for managing knowledge base sections."""

    def __init__(
        self, host: str = "localhost", port: int = 27017, database: str = "test"
    ) -> None:
        self.client: MongoClient = MongoClient(host, port)
        self.db: Database = self.client[database]
        self.collection: Collection = self.db.sections
        self._create_indexes()

    def _create_indexes(self) -> None:
        """Create indexes for efficient queries if they don't exist."""
        existing_indexes: set[str] = set(self.collection.index_information().keys())

        if "section_id_1" not in existing_indexes:
            self.collection.create_index([("section_id", ASCENDING)], unique=True)

        if "parent_id_1" not in existing_indexes:
            self.collection.create_index([("parent_id", ASCENDING)])

        if "slug_1" not in existing_indexes:
            self.collection.create_index([("slug", ASCENDING)])

        if "header_1" not in existing_indexes:
            self.collection.create_index([("header", ASCENDING)])

    def add(
        self,
        header: str,
        content: str,
        parent_id: str | None = None,
        slug: str | None = None,
    ) -> str:
        """Add a new section to the knowledge base."""
        section_id: str = generate_id()

        # Determine order and level
        level: int
        if parent_id:
            parent: Section | None = self.get(parent_id)
            if not parent:
                raise ValueError(f"Parent section '{parent_id}' not found")
            level = parent.level + 1
        else:
            level = 0

        siblings: list[Section] = self.get_children(parent_id)
        order: int = len(siblings)

        section: Section = Section(
            section_id=section_id,
            parent_id=parent_id,
            slug=slug or slugify(header),
            header=header,
            content=content,
            level=level,
            order=order,
        )

        self.collection.insert_one(section.model_dump())
        return section_id

    def get(self, section_id: str) -> Section | None:
        """Get a section by its ID."""
        doc: dict | None = self.collection.find_one({"section_id": section_id})
        return Section(**doc) if doc else None

    def get_by_slug(self, slug: str) -> Section | None:
        """Get a section by its slug."""
        doc: dict | None = self.collection.find_one({"slug": slug})
        return Section(**doc) if doc else None

    def get_by_path(self, path: str) -> Section | None:
        """Get a section by numeric path like '1.2.3'."""
        all_sections: list[Section] = self.list_all()
        parts: list[int] = [int(p) for p in path.split(".")]

        current_parent: str | None = None
        for position in parts:
            siblings: list[Section] = [
                s for s in all_sections if s.parent_id == current_parent
            ]
            siblings.sort(key=lambda s: s.order)

            if position < 1 or position > len(siblings):
                return None

            current_parent = siblings[position - 1].section_id

        return self.get(current_parent) if current_parent else None

    def get_by_header(self, header: str) -> list[Section]:
        """Get sections by header name (may return multiple matches)."""
        docs = self.collection.find({"header": header})
        return [Section(**doc) for doc in docs]

    def get_children(self, parent_id: str | None = None) -> list[Section]:
        """Get all direct children of a section."""
        docs = self.collection.find({"parent_id": parent_id}).sort("order", ASCENDING)
        return [Section(**doc) for doc in docs]

    def list_all(self) -> list[Section]:
        """Get all sections."""
        docs = self.collection.find()
        return [Section(**doc) for doc in docs]

    def update(
        self,
        section_id: str,
        header: str | None = None,
        content: str | None = None,
    ) -> bool:
        """Update a section's header or content."""
        updates: dict[str, str | datetime] = {"updated_at": datetime.utcnow()}
        if header is not None:
            updates["header"] = header
            updates["slug"] = slugify(header)
        if content is not None:
            updates["content"] = content

        result: UpdateResult = self.collection.update_one(
            {"section_id": section_id}, {"$set": updates}
        )
        return result.modified_count > 0

    def delete(self, section_id: str, recursive: bool = False) -> bool:
        """Delete a section and optionally its children."""
        if recursive:
            # Delete all descendants
            to_delete: list[str] = [section_id]
            processed: set[str] = set()

            while to_delete:
                current_id: str = to_delete.pop()
                if current_id in processed:
                    continue

                processed.add(current_id)
                children: list[Section] = self.get_children(current_id)
                to_delete.extend([c.section_id for c in children])

            self.collection.delete_many({"section_id": {"$in": list(processed)}})
            return True
        else:
            # Check if has children
            if self.get_children(section_id):
                raise ValueError(
                    f"Section '{section_id}' has children. Use recursive=True to delete all."
                )

            result: DeleteResult = self.collection.delete_one(
                {"section_id": section_id}
            )
            return result.deleted_count > 0

    def export_tree(self, section_id: str | None = None) -> str:
        """Export section tree as formatted text."""
        sections: list[Section]
        if section_id:
            # Export specific section and its descendants
            section: Section | None = self.get(section_id)
            if not section:
                raise ValueError(f"Section '{section_id}' not found")

            # Get all descendants
            sections = [section]
            to_process: list[str] = [section_id]
            while to_process:
                current: str = to_process.pop()
                children: list[Section] = self.get_children(current)
                sections.extend(children)
                to_process.extend([c.section_id for c in children])
        else:
            # Export entire tree
            sections = self.list_all()

        return format_section_tree(sections)

    def export_to_file(self, filepath: str, section_id: str | None = None) -> None:
        """Export section tree to a text file."""
        content: str = self.export_tree(section_id)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    def close(self) -> None:
        """Close the MongoDB connection."""
        self.client.close()
