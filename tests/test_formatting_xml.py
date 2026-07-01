"""Tests for minerva.formatting."""

from pathlib import Path

import yaml

from minerva.formatting import to_float, xml_to_yaml


class TestToFloat:
    """Tests for to_float coercion."""

    def test_plain_number(self):
        assert to_float(292.46) == 292.46
        assert to_float(5) == 5.0

    def test_none_and_empty_return_none(self):
        assert to_float(None) is None
        assert to_float("") is None

    def test_strips_financial_noise(self):
        assert to_float("1,234.5") == 1234.5
        assert to_float("12.5%") == 12.5
        assert to_float("  42 ") == 42.0

    def test_unparseable_returns_none(self):
        assert to_float("n/a") is None
        assert to_float(object()) is None


class TestXmlToYaml:
    """Tests for xml_to_yaml round-trip conversion."""

    def test_round_trip(self, tmp_dir: Path):
        """Write XML, convert to YAML, read back, verify content."""
        xml_content: str = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<root>"
            "  <company>Acme Corp</company>"
            "  <revenue>1000000</revenue>"
            "  <year>2025</year>"
            "</root>"
        )
        xml_path: Path = tmp_dir / "data.xml"
        xml_path.write_text(xml_content, encoding="utf-8")

        yaml_path: Path = xml_to_yaml(xml_path)

        assert yaml_path.exists()
        assert yaml_path.suffix == ".yaml"

        with open(yaml_path, encoding="utf-8") as f:
            parsed: dict = yaml.safe_load(f)

        assert parsed["root"]["company"] == "Acme Corp"
        assert parsed["root"]["revenue"] == "1000000"
        assert parsed["root"]["year"] == "2025"

    def test_custom_output_path(self, tmp_dir: Path):
        """Respects explicit yaml_path argument."""
        xml_content: str = "<item><name>Widget</name></item>"
        xml_path: Path = tmp_dir / "input.xml"
        xml_path.write_text(xml_content, encoding="utf-8")

        custom_out: Path = tmp_dir / "custom_output.yaml"
        result_path: Path = xml_to_yaml(xml_path, yaml_path=custom_out)

        assert result_path == custom_out
        assert custom_out.exists()

        with open(custom_out, encoding="utf-8") as f:
            parsed: dict = yaml.safe_load(f)
        assert parsed["item"]["name"] == "Widget"

    def test_default_path_replaces_suffix(self, tmp_dir: Path):
        """Default output path replaces .xml with .yaml."""
        xml_path: Path = tmp_dir / "report.xml"
        xml_path.write_text("<doc><title>Test</title></doc>", encoding="utf-8")

        result_path: Path = xml_to_yaml(xml_path)
        expected: Path = tmp_dir / "report.yaml"
        assert result_path == expected
