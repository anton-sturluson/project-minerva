"""Main Knowledge Base interface combining MongoDB and Chroma."""

from typing import Optional, List, Dict, Any

from .mongo import MongoKB
from .chroma import ChromaKB
from .models import Section, QueryResult
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
    ):
        self.mongo = MongoKB(host=mongo_host, port=mongo_port, database=mongo_database)
        self.chroma = ChromaKB(path=chroma_path, collection_name=chroma_collection)

    def add(
        self,
        header: str,
        content: str,
        parent_section: Optional[str] = None,
        slug: Optional[str] = None,
    ) -> str:
        """Add knowledge to both MongoDB and Chroma."""
        # Add to MongoDB
        section_id = self.mongo.add(
            header=header, content=content, parent_id=parent_section, slug=slug
        )

        # Get the section to build metadata
        section = self.mongo.get(section_id)
        if not section:
            raise ValueError(f"Failed to create section '{section_id}'")

        # Add to Chroma with metadata
        metadata = {
            "section_id": section_id,
            "header": header,
            "level": section.level,
            "parent_id": parent_section or "",
        }
        self.chroma.add(section_id=section_id, content=content, metadata=metadata)

        return section_id

    def get(self, identifier: str) -> Optional[Section]:
        """Get a section by ID, slug, or numeric path."""
        # Try as section_id first
        section = self.mongo.get(identifier)
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

    def get_by_header(self, header: str) -> List[Section]:
        """Get sections by header name."""
        return self.mongo.get_by_header(header)

    def update(
        self,
        identifier: str,
        header: Optional[str] = None,
        content: Optional[str] = None,
    ) -> bool:
        """Update a section in both MongoDB and Chroma."""
        section = self.get(identifier)
        if not section:
            return False

        # Update MongoDB
        success = self.mongo.update(section.section_id, header=header, content=content)

        # Update Chroma if content changed
        if content is not None:
            updated_section = self.mongo.get(section.section_id)
            if updated_section:
                metadata = {
                    "section_id": section.section_id,
                    "header": updated_section.header,
                    "level": updated_section.level,
                    "parent_id": updated_section.parent_id or "",
                }
                self.chroma.update(section.section_id, content, metadata)

        return success

    def delete(self, identifier: str, recursive: bool = False) -> bool:
        """Delete a section from both MongoDB and Chroma."""
        section = self.get(identifier)
        if not section:
            return False

        if recursive:
            # Get all descendants to delete from Chroma
            sections_to_delete = [section.section_id]
            to_process = [section.section_id]

            while to_process:
                current = to_process.pop()
                children = self.mongo.get_children(current)
                child_ids = [c.section_id for c in children]
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
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[QueryResult]:
        """Search for knowledge using semantic similarity."""
        # Search in Chroma
        results = self.chroma.search(
            query, n_results=n_results, metadata_filter=metadata_filter
        )

        # Enrich results with MongoDB data
        enriched = []
        all_sections = self.mongo.list_all()

        for result in results:
            section = self.mongo.get(result.section_id)
            if section:
                # Build path for the section
                path = build_section_path(section, all_sections)
                result.path = path
                enriched.append(result)

        return enriched

    def get_children(self, parent_identifier: Optional[str] = None) -> List[Section]:
        """Get all direct children of a section."""
        if parent_identifier:
            parent = self.get(parent_identifier)
            if not parent:
                return []
            parent_id = parent.section_id
        else:
            parent_id = None

        return self.mongo.get_children(parent_id)

    def get_tree(self, root_identifier: Optional[str] = None) -> str:
        """Get formatted tree structure."""
        if root_identifier:
            root = self.get(root_identifier)
            if not root:
                raise ValueError(f"Section '{root_identifier}' not found")
            return self.mongo.export_tree(root.section_id)
        else:
            return self.mongo.export_tree()

    def export(self, filepath: str, root_identifier: Optional[str] = None):
        """Export knowledge base tree to a text file."""
        if root_identifier:
            root = self.get(root_identifier)
            if not root:
                raise ValueError(f"Section '{root_identifier}' not found")
            self.mongo.export_to_file(filepath, root.section_id)
        else:
            self.mongo.export_to_file(filepath)

    def close(self):
        """Close all database connections."""
        self.mongo.close()
