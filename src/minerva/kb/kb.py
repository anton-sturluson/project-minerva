"""Main Knowledge Base interface combining MongoDB and Chroma."""

from typing import Any

from .mongo import MongoKB
from .chroma import ChromaKB
from .model import Section, QueryResult
from .utils import build_section_path


class KnowledgeBase:
    """Unified interface for knowledge base operations using MongoDB and Chroma."""

    def __init__(
        self,
        mongo_host: str = "localhost",
        mongo_port: int = 27017,
        mongo_database: str = "test",
        chroma_path: str = "./.chroma_db",
        chroma_collection: str = "knowledge_base",
    ) -> None:
        self.mongo: MongoKB = MongoKB(
            host=mongo_host, port=mongo_port, database=mongo_database
        )
        self.chroma: ChromaKB = ChromaKB(
            path=chroma_path, collection_name=chroma_collection
        )

    def add(
        self,
        header: str,
        content: str,
        parent_section: str | None = None,
        slug: str | None = None,
    ) -> str:
        """Add knowledge to both MongoDB and Chroma."""
        # Add to MongoDB
        section_id: str = self.mongo.add(
            header=header, content=content, parent_id=parent_section, slug=slug
        )

        # Get the section to build metadata
        section: Section | None = self.mongo.get(section_id)
        if not section:
            raise ValueError(f"Failed to create section '{section_id}'")

        # Add to Chroma with metadata
        metadata: dict[str, Any] = {
            "section_id": section_id,
            "header": header,
            "level": section.level,
            "parent_id": parent_section or "",
        }
        self.chroma.add(section_id=section_id, content=content, metadata=metadata)

        return section_id

    def get(self, identifier: str) -> Section | None:
        """Get a section by ID, slug, or numeric path."""
        # Try as section_id first
        section: Section | None = self.mongo.get(identifier)
        if section:
            return section

        # Try as slug
        section = self.mongo.get_by_slug(identifier)
        if section:
            return section

        # Try as numeric path (e.g., "1.2.3")
        if "." in identifier and all(p.isdigit() for p in identifier.split(".")):
            section = self.mongo.get_by_path(identifier)
            if section:
                return section

        return None

    def get_by_header(self, header: str) -> list[Section]:
        """Get sections by header name."""
        return self.mongo.get_by_header(header)

    def update(
        self,
        identifier: str,
        header: str | None = None,
        content: str | None = None,
    ) -> bool:
        """Update a section in both MongoDB and Chroma."""
        section: Section | None = self.get(identifier)
        if not section:
            return False

        # Update MongoDB
        success: bool = self.mongo.update(
            section.section_id, header=header, content=content
        )

        # Update Chroma if content changed
        if content is not None:
            updated_section: Section | None = self.mongo.get(section.section_id)
            if updated_section:
                metadata: dict[str, Any] = {
                    "section_id": section.section_id,
                    "header": updated_section.header,
                    "level": updated_section.level,
                    "parent_id": updated_section.parent_id or "",
                }
                self.chroma.update(section.section_id, content, metadata)

        return success

    def delete(self, identifier: str, recursive: bool = False) -> bool:
        """Delete a section from both MongoDB and Chroma."""
        section: Section | None = self.get(identifier)
        if not section:
            return False

        if recursive:
            # Get all descendants to delete from Chroma
            sections_to_delete: list[str] = [section.section_id]
            to_process: list[str] = [section.section_id]

            while to_process:
                current: str = to_process.pop()
                children: list[Section] = self.mongo.get_children(current)
                child_ids: list[str] = [c.section_id for c in children]
                sections_to_delete.extend(child_ids)
                to_process.extend(child_ids)

            # Delete from Chroma
            for sid in sections_to_delete:
                self.chroma.delete(sid)
        else:
            # Delete from Chroma
            self.chroma.delete(section.section_id)

        # Delete from MongoDB
        return self.mongo.delete(section.section_id, recursive=recursive)

    def search(
        self,
        query: str,
        n_results: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[QueryResult]:
        """Search for knowledge using semantic similarity."""
        # Search in Chroma
        results: list[QueryResult] = self.chroma.search(
            query, n_results=n_results, metadata_filter=metadata_filter
        )

        # Enrich results with MongoDB data
        enriched: list[QueryResult] = []
        all_sections: list[Section] = self.mongo.list_all()

        for result in results:
            section: Section | None = self.mongo.get(result.section_id)
            if section:
                # Build path for the section
                path: str = build_section_path(section, all_sections)
                result.path = path
                enriched.append(result)

        return enriched

    def get_children(self, parent_identifier: str | None = None) -> list[Section]:
        """Get all direct children of a section."""
        parent_id: str | None
        if parent_identifier:
            parent: Section | None = self.get(parent_identifier)
            if not parent:
                return []
            parent_id = parent.section_id
        else:
            parent_id = None

        return self.mongo.get_children(parent_id)

    def get_tree(self, root_identifier: str | None = None) -> str:
        """Get formatted tree structure."""
        if root_identifier:
            root: Section | None = self.get(root_identifier)
            if not root:
                raise ValueError(f"Section '{root_identifier}' not found")
            return self.mongo.export_tree(root.section_id)
        else:
            return self.mongo.export_tree()

    def export(self, filepath: str, root_identifier: str | None = None) -> None:
        """Export knowledge base tree to a text file."""
        if root_identifier:
            root: Section | None = self.get(root_identifier)
            if not root:
                raise ValueError(f"Section '{root_identifier}' not found")
            self.mongo.export_to_file(filepath, root.section_id)
        else:
            self.mongo.export_to_file(filepath)

    def set_collection(self, collection_name: str) -> None:
        """Switch to a different collection."""
        self.mongo.collection = self.mongo.db[collection_name.lower()]
        self.chroma.collection = self.chroma.client.get_or_create_collection(
            name=collection_name
        )

    def close(self) -> None:
        """Close all database connections."""
        self.mongo.close()
