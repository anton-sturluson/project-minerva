"""Utility functions for reading and writing files to S3 or local disk."""
__all__ = ["File", "S3Url"]

from collections.abc import Iterable
from io import BytesIO, StringIO
import json
from pathlib import Path
import pickle
from typing import Any, Iterator
from urllib.parse import urlparse
import yaml

import botocore
from botocore.config import Config
from botocore.exceptions import ClientError
from bson import json_util
import boto3
import pandas as pd

from aitoolkit.fileio.encoder import FileJSONEncoder


config = Config(connect_timeout=20, read_timeout=120)
s3 = boto3.resource("s3", config=config)


class S3Url:
    """
    Pasted from https://stackoverflow.com/questions/42641315/s3-urls-get-bucket-name-and-path

    >>> s = S3Url("s3://bucket/hello/world")
    >>> s.bucket
    'bucket'
    >>> s.key
    'hello/world'
    >>> s.url
    's3://bucket/hello/world'

    >>> s = S3Url("s3://bucket/hello/world?qwe1=3#ddd")
    >>> s.bucket
    'bucket'
    >>> s.key
    'hello/world?qwe1=3#ddd'
    >>> s.url
    's3://bucket/hello/world?qwe1=3#ddd'

    >>> s = S3Url("s3://bucket/hello/world#foo?bar=2")
    >>> s.key
    'hello/world#foo?bar=2'
    >>> s.url
    's3://bucket/hello/world#foo?bar=2'
    """
    def __init__(self, url: str):
        self.url = url
        self._parsed = urlparse(url, allow_fragments=False)

    @property
    def bucket(self):
        """Return the bucket name."""
        return self._parsed.netloc

    @property
    def key(self):
        """Return the key."""
        if self._parsed.query:
            return self._parsed.path.lstrip('/') + '?' + self._parsed.query
        return self._parsed.path.lstrip('/')

    @property
    def stem(self) -> str:
        """Return the stem."""
        return self.url.split("/")[-1]

    @property
    def suffix(self) -> str:
        """Return the suffix."""
        return "." + self.key.split(".")[-1]

    def __str__(self):
        """Return the URL."""
        return self.url

    def __repr__(self):
        """Return the URL."""
        return f"S3Url({self.url})"

    def __truediv__(self, path_to_add: str) -> "S3Url":
        """Add path to the current path."""
        url = self.url
        if url.endswith("/"):
            url = url.rstrip("/")

        if path_to_add.startswith("/"):
            path_to_add = path_to_add.lstrip("/")

        return S3Url(f"{url}/{path_to_add}")


class File:
    """Class to load and save a file(s) from S3 or local disk.

    Attributes:
        path: path to file (PosixPath or S3Url)
        encoding: encoding to use when reading and writing files
            (default: "utf-8")
    """
    def __init__(
        self,
        path: str | Path | S3Url,
        encoding: str = "utf-8"
    ):
        if isinstance(path, str):
            if path.startswith("s3"):
                path = S3Url(path)
            else:
                path = Path(path)

        elif isinstance(path, File):
            path = path.path

        self.path = path
        self.encoding = encoding

    def __str__(self):
        return str(self.path)

    def __repr__(self):
        return f"File({str(self)})"

    @property
    def is_local(self) -> bool:
        """Check if the file is in local disk."""
        return not isinstance(self.path, S3Url)

    def __truediv__(self, path_to_add: str) -> "File":
        """Add path to the current path (consistent with Pathlib)."""
        return File(self.path / path_to_add)

    @property
    def exists(self) -> bool:
        """Check if the file exists."""
        if self.is_local:
            return self.exists_in_local()
        return self.exists_in_s3()

    def exists_in_local(self) -> bool:
        """Check if the file exists in local disk."""
        return self.path.exists()

    def exists_in_s3(self) -> bool:
        """Check if the file exists in S3."""
        bucket = s3.Bucket(self.path.bucket)
        for obj in bucket.objects.filter(Prefix=self.path.key, MaxKeys=1):
            return True
        return False

    def load(self):
        """Load data from S3 or local disk."""
        if isinstance(self.path, S3Url):
            out: bytes | None = self.read_from_s3()
        else:
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

        elif self.path.suffix in [".yml", ".yaml"]:
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
        if isinstance(self.path, S3Url):
            self.write_to_s3(data, indent)
        else:
            self.write_to_local(data, indent)

    def read_from_local(self) -> bytes | None:
        """Load bytes data from local disk."""
        try:
            with self.path.open("rb") as f:
                return f.read()
        except FileNotFoundError:
            print(f"`read_from_local`: Failed to find file: {self.path}")
            return None

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
            if not isinstance(data, Iterable):
                raise ValueError("Data must be an iterable")

            with self.path.open("w", encoding=self.encoding) as f:
                for i, item in enumerate(data):
                    if i == len(data) - 1:
                        write: str = json.dumps(item, cls=FileJSONEncoder)
                    else:
                        write: str = json.dumps(item, cls=FileJSONEncoder)+"\n"
                    f.write(write)
            return

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

    def read_from_s3(self) -> bytes:
        """Return S3 object given load path."""
        s3_obj = s3.Object(self.path.bucket, self.path.key)
        try:
            return s3_obj.get()["Body"].read()
        except s3.meta.client.exceptions.NoSuchBucket:
            print(f"`get_object`: Failed to find bucket: {self.path.bucket}")
        except s3.meta.client.exceptions.NoSuchKey:
            print(f"`get_object`: Failed to find object: {self.path}")
        except s3.meta.client.exceptions.ClientError:
            print("`get_object`: Ensure that access to the path: "
                  f"{self.path}")

        return None

    def write_to_s3(self, data: Any, indent: int | None = None):
        """Upload object to S3."""
        bucket = s3.Bucket(self.path.bucket)
        dumped_data = None
        content_type: str = "application/octet-stream"
        if self.path.suffix == ".json":
            content_type = "application/json"
            dumped_data = json.dumps(data, indent=indent, cls=FileJSONEncoder)

        elif self.path.suffix == ".jsonl":
            content_type = "application/jsonl"
            if not isinstance(data, Iterable):
                raise ValueError("Data must be an iterable for .jsonl files")
            # Convert each item to JSON and join with newlines
            dumped_data = "\n".join(
                json.dumps(item, cls=FileJSONEncoder) for item in data
            ).encode(self.encoding)

        elif self.path.suffix in [".yaml", ".yml"]:
            # dump using custom encoder
            tmp_dumped_data: str = json.dumps(
                data, indent=indent, cls=FileJSONEncoder)
            # and load it back
            reloaded_data: dict = json.loads(
                tmp_dumped_data, object_hook=json_util.object_hook)

            content_type = "application/x-yaml"
            dumped_data = yaml.dump(reloaded_data)

        elif isinstance(data, pd.DataFrame):
            csv_buffer = StringIO()
            sep = None
            if self.path.suffix == ".csv":
                content_type = "test/csv"
                sep = ","
            elif self.path.suffix == ".tsv":
                content_type = "test/tsv"
                sep = "\t"
            if sep:
                # Get the CSV string as bytes
                data.to_csv(csv_buffer, index=False, sep=sep)
                dumped_data = csv_buffer.getvalue().encode(self.encoding)

        if not dumped_data:
            dumped_data = data
            if not isinstance(data, bytes):
                dumped_data = pickle.dumps(data)

        try:
            bucket.put_object(
                Key=self.path.key,
                Body=dumped_data,
                ContentType=content_type)

        except botocore.exceptions.ClientError as e:
            # Handle permissions, missing bucket, etc.
            print(f"ClientError: {e.response['Error']['Message']}")

        except botocore.exceptions.EndpointConnectionError as e:
            print(f"Endpoint connection error, check your network or "
                  "region configuration.: {e}")

        except botocore.exceptions.ParamValidationError as e:
            print(f"Parameter validation error: {e}")

        except botocore.exceptions.ReadTimeoutError:
            print(f"Read timeout error: The server took too long to respond. {e}")

        except botocore.exceptions.S3UploadFailedError:
            print(f"Upload failed: Network or connection issue. {e}")

        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    def download_from_s3(self, save_path: str | Path):
        """Download file from S3."""
        s3_obj = s3.Object(self.path.bucket, self.path.key)
        s3_obj.download_file(save_path)

    def startswith(self, prefix: str | tuple[str]) -> bool:
        """Check if the path starts with the given prefix."""
        return str(self.path).startswith(prefix)

    def endswith(self, suffix: str | tuple[str]) -> bool:
        """Check if the path ends with the given suffix."""
        return str(self.path).endswith(suffix)

    def list_files(self) -> Iterator["File"]:
        """List files in directory."""
        if isinstance(self.path, S3Url):
            return self.list_files_in_s3()
        else:
            return self.list_files_in_local()

    def list_files_in_local(self) -> Iterator["File"]:
        """List full file paths in local directory."""
        for f in self.path.iterdir():
            yield File(f)

    def list_files_in_s3(self) -> Iterator["File"]:
        """
        List full file paths in S3 bucket. Note that this can take a while
        if there are many files starting with the same prefix.
        """
        bucket = s3.Bucket(self.path.bucket)
        for obj in bucket.objects.filter(Prefix=self.path.key):
            # uncomment this line if we want to limit to the first level
            # rest_path = obj.key.lstrip(self.path.key).lstrip("/")
            # if "/" in rest_path:
                # continue
            yield File(f"s3://{self.path.bucket}/{obj.key}")

    def mkdir(self, parents: bool = False):
        """
        Create directory in S3 or local disk. Ignore if directory is in S3
        or already exists in local disk.

        Args:
            parents: whether to create parent directories
        """
        if self.is_local and not self.exists:
            self.path.mkdir(parents=parents)
