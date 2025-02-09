# Minerva Knowledge

A Python package for managing and processing document knowledge bases, with support for vector databases and LLM operations.

## Installation

### From Source
```bash
git clone https://github.com/yourusername/proejct-minerva.git
cd proejct-minerva/knowledge-base
pip install -e .
```

### Development Installation
For development, install with additional development dependencies:
```bash
pip install -e ".[dev]"
```

## Usage

```python
from knowledge.database import KB
from knowledge.llm import chunk_text, get_embeddings
from knowledge.util import load_file

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
