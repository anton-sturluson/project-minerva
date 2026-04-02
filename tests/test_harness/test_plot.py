"""Tests for plot commands."""

from pathlib import Path

from harness.commands.plot import create_plot
from harness.config import HarnessSettings


def test_plot_command_creates_image_file(tmp_path: Path) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("label,value\nA,1\nB,2\n", encoding="utf-8")

    result = create_plot(
        chart_type="bar",
        data_path="data.csv",
        x_column="label",
        y_column="value",
        output_path="plots/test.png",
        settings=settings,
    )

    assert result.exit_code == 0
    assert (tmp_path / "plots" / "test.png").exists()
