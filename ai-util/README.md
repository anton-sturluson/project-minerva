# AI Toolkit

This repo contains various utility functions as a toolkit for Jona's AI team.

## Dependencies
* Python version should be 3.10 or higher.
* Install `poetry`, a Python package manager for managing dependencies [here](https://python-poetry.org/docs/#installing-with-the-official-installer).

## Installation

```shell
git clone git@github.com:jonahealth/jona-ai.git
cd jona-ai/ai-util
poetry install
```

## Usage

```python
from aitoolkit.io import File

# Read a csv file from S3
# it automatically reads a TSV file with Pandas
cosmos_sample_df = File("s3://cosmosid-data/labcorp-samples/LC002M/2.tsv").load()

# Read a JSON file from S3
disease_stat_dict = File("s3://jona-ai/data/gmrepo-data/processing-output/disease-statistics.json").load()

# Also reads anything from local
local_file = File("/path/to/data").load()
```
