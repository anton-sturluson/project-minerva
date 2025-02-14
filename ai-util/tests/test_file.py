import pandas as pd
import pytest

from aitoolkit.fileio import File, S3Url


def test_s3url():
    s = S3Url("s3://bucket/hello/world")
    assert s.bucket == "bucket"
    assert s.key == "hello/world"
    assert s.url == "s3://bucket/hello/world"
    assert str(s) == "s3://bucket/hello/world"
    assert str(s / "foo") == "s3://bucket/hello/world/foo"
    assert s.stem == "world"

    s = S3Url("s3://bucket")
    assert s.bucket == "bucket"
    assert s.key == ""
    assert s.stem == "bucket"


def test_file():
    file = File("test_file.py")
    assert file.is_local
    assert not file.exists
    assert file.encoding == "utf-8"

    file = File("tests/test_file.txt")
    assert file.is_local
    assert file.exists
    assert file.load() == "test prompt\n"

    file = File("s3://jona-ai/data/crohns/C3001C20/C3001C20_bacteria_filtered.tsv")
    assert isinstance(file.load(), pd.DataFrame)

    dir_ = File("s3://jona-ai/data/crohns/C3001C20/")
    assert not dir_.is_local
    assert dir_.exists
    assert (
        [str(x) for x in dir_.list_files()]
        == [str(dir_ / "/C3001C20_bacteria_filtered.tsv")])
    assert str(dir_ / "new.csv") == "s3://jona-ai/data/crohns/C3001C20/new.csv"

    dir_ = File("src")
    assert dir_.is_local
    assert [str(x) for x in dir_.list_files()] == ["src/aitoolkit"]
