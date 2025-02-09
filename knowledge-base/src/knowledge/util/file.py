"""Utility functions for reading and writing files to S3 or local disk."""
from io import BytesIO
import json
from pathlib import Path
import pickle
from typing import Any, Iterator

from bson import json_util
import yaml
import pandas as pd

from knowledge.util.encoder import FileJSONEncoder


class File:
    """Class to load and save a file(s) from S3 or local disk.

    Attributes:
        path: path to file (PosixPath or S3Url)
        encoding: encoding to use when reading and writing files
            (default: "utf-8")
    """
    def __init__(
        self,
        path: str | Path,
        encoding: str = "utf-8"
    ):
        if isinstance(path, str):
            path = Path(path)

        elif isinstance(path, File):
            path = path.path

        self.path = path
        self.encoding = encoding

    def __str__(self):
        return str(self.path)

    def __repr__(self):
        return f"File({str(self)})"

    def __truediv__(self, path_to_add: str) -> "File":
        """Add path to the current path (consistent with Pathlib)."""
        return File(self.path / path_to_add)

    @property
    def exists(self) -> bool:
        """Check if the file exists."""
        return self.path.exists()

    def load(self):
        """Load data from local disk."""
        out: bytes | None = self.read_from_local()
        if out is None:
            return out

        if self.path.suffix == ".json":
            out = json.loads(
                out.decode(self.encoding), object_hook=json_util.object_hook)

        elif self.path.suffix == ".jsonl":
            tmp_lst = []
            for line in out.decode(self.encoding).split("\n"):
                if line:
                    tmp_lst.append(
                        json.loads(line, object_hook=json_util.object_hook))
            out = tmp_lst

        elif self.path.suffix in [".yaml", ".yml"]:
            yaml_str: str = out.decode(self.encoding)
            out = yaml.safe_load(yaml_str)

        elif self.path.suffix == ".csv":
            out = pd.read_csv(BytesIO(out))

        elif self.path.suffix == ".tsv":
            out = pd.read_csv(BytesIO(out), sep="\t")

        elif self.path.suffix == ".pkl":
            out = pickle.loads(out)

        if isinstance(out, bytes):
            out = out.decode(self.encoding)

        return out

    def save(
        self,
        data: Any,
        indent: int | None = None
    ):
        """Save data to S3 or local disk.

        Args:
            data: data to save
            indent: indentation level for JSON data. Applicable only
                if `is_json` is True.
        """
        self.write_to_local(data, indent)

    def read_from_local(self) -> bytes:
        """Load bytes data from local disk."""
        with self.path.open("rb") as f:
            return f.read()

    def write_to_local(
        self, data: Any,
        indent: int | None = None
    ):
        """Save data to local disk in bytes."""
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True)

        if self.path.suffix == ".json":
            try:
                dumped_data = data
                if not isinstance(dumped_data, str):
                    dumped_data: str = json.dumps(
                        data, indent=indent, cls=FileJSONEncoder)
                with self.path.open("w", encoding=self.encoding) as f:
                    f.write(dumped_data)
                return

            except Exception as e:
                print("Failed to write JSON file: ", e)

        elif self.path.suffix == ".jsonl":
            try:
                with self.path.open("w", encoding=self.encoding) as f:
                    for line in data:
                        f.write(json.dumps(line) + "\n")
                return

            except Exception as e:
                print("Failed to write JSONL file: ", e)

        elif self.path.suffix in [".yaml", ".yml"]:
            try:
                if isinstance(data, str):
                    dumped_data: str = data
                else:
                    # dump using custom encoder
                    dumped_data: str = yaml.dump(data)
                with self.path.open("w", encoding=self.encoding) as f:
                    f.write(dumped_data)
                return

            except Exception as e:
                print("Failed to write YAML file: ", e)

        elif isinstance(data, pd.DataFrame):
            sep = None
            if self.path.suffix == ".csv":
                sep = ","
            elif self.path.suffix == ".tsv":
                sep = "\t"
            if sep:
                data.to_csv(self.path, index=False, sep=sep)
                return

        dumped_data = data
        if not isinstance(data, bytes):
            dumped_data = pickle.dumps(data)

        with self.path.open("wb") as f:
            f.write(dumped_data)

    def startswith(self, prefix: str | tuple[str]) -> bool:
        """Check if the path starts with the given prefix."""
        return str(self.path).startswith(prefix)

    def endswith(self, suffix: str | tuple[str]) -> bool:
        """Check if the path ends with the given suffix."""
        return str(self.path).endswith(suffix)

    def list_files(self) -> Iterator["File"]:
        """List files in directory."""
        return self.list_files_in_local()

    def list_files_in_local(self) -> Iterator["File"]:
        """List full file paths in local directory."""
        for f in self.path.iterdir():
            yield File(f)

    def mkdir(self, parents: bool = False):
        """
        Create directory in S3 or local disk. Ignore if directory is in S3
        or already exists in local disk.

        Args:
            parents: whether to create parent directories
        """
        if not self.exists:
            self.path.mkdir(parents=parents)
