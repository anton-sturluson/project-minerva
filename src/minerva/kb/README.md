# Knowledge Base

Hierarchical knowledge base with MongoDB (structured storage) and Chroma (semantic search).

## Installation

```bash
pip install -r requirements.txt
```

Ensure MongoDB is running on `localhost:27017`.

## Quick Start

```python
from minerva.kb import KnowledgeBase

kb = KnowledgeBase()

# Add sections
report_id = kb.add("Annual Report 2024", "Report content...")
revenue_id = kb.add("Revenue Analysis", "Revenue details...", parent_section=report_id)

# Query by ID, path, or slug
section = kb.get(revenue_id)           # By UUID
section = kb.get("1.1")                # By path
section = kb.get("revenue-analysis")   # By slug

# Semantic search
results = kb.search("What was the revenue?", n_results=5)

# Export
kb.export("output.txt")
kb.close()
```

## Key Methods

- `add(header, content, parent_section=None, slug=None)` - Add section
- `get(identifier)` - Get by ID/path/slug
- `update(identifier, header=None, content=None)` - Update section
- `delete(identifier, recursive=False)` - Delete section
- `search(query, n_results=5)` - Semantic search
- `get_children(parent_identifier=None)` - Get child sections
- `export(filepath, root_identifier=None)` - Export to file

## Data Schema

**MongoDB**: Hierarchical structure with UUIDs, slugs, and ordering
**Chroma**: Auto-chunked content (500 chars) with embeddings

See `example.py` for detailed usage.
