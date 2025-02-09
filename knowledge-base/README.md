# Minerva Knowledge

A Python package for managing and processing document knowledge bases, with support for vector databases and LLM operations.

## Installation

### From Source
```bash
git clone https://github.com/a-sturluson/project-minerva.git
cd project-minerva/knowledge-base
pip install -e .
```

### Development Installation
For development, install with additional development dependencies:
```bash
pip install -e ".[dev]"
```

## Usage

```python
from minerva_knowledge.database import KB
from minerva_knowledge.llm import chunk_text, get_embeddings
from minerva_knowledge.util import load_file

# Initialize knowledge base
kb = KB()

# Process documents
text = load_file("path/to/document.txt")
chunks = chunk_text(text)
embeddings = get_embeddings(chunks)

# Store in vector database
kb.store_embeddings(embeddings)
```

## Features

- Document processing and chunking
- Vector database integration (Milvus)
- LLM utilities for text processing
- File handling utilities
- MongoDB integration for metadata storage

## Development

1. Install development dependencies: `pip install -e ".[dev]"`
2. Run tests: `pytest tests/`
3. Format code: `black . && isort .`

## License

MIT
