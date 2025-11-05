"""Parser for earnings call transcripts."""

from collections.abc import Coroutine
import asyncio
import re

from minerva.parser.base import BaseParser, Line, ParsedOutput
from minerva.prompt.metric.unary import operator_instruction_metric, boilerplate_metric
from minerva.prompt.metric.model import MetricResult


class TranscriptLine(Line):
    """A single line from an earnings call transcript."""

    speaker: str
    is_operator: bool


class TranscriptParser(BaseParser):
    """Parser for earnings call transcripts."""

    def _parse_line(self, index: int, line: str) -> TranscriptLine | None:
        """Parse a single line to extract speaker and text."""
        match: re.Match[str] | None = re.match(r"^([^:]+):\s*(.*)$", line)
        if not match:
            return None

        speaker: str = match.group(1).strip()
        text: str = match.group(2).strip()
        is_operator: bool = speaker.lower() == "operator"

        return TranscriptLine(
            index=index, text=text, speaker=speaker, is_operator=is_operator
        )

    async def _identify_special_lines(
        self, transcript_lines: list[TranscriptLine]
    ) -> tuple[list[int], set[int]]:
        """Identify operator instruction lines and boilerplate lines."""
        operator_lines: list[TranscriptLine] = [
            line for line in transcript_lines if line.is_operator
        ]
        non_operator_lines: list[TranscriptLine] = [
            line for line in transcript_lines if not line.is_operator
        ]

        operator_tasks: list[Coroutine] = [
            operator_instruction_metric(line.text) for line in operator_lines
        ]
        boilerplate_tasks: list[Coroutine] = [
            boilerplate_metric(line.text) for line in non_operator_lines
        ]

        operator_results: list[MetricResult]
        boilerplate_results: list[MetricResult]
        operator_results, boilerplate_results = await asyncio.gather(
            asyncio.gather(*operator_tasks), asyncio.gather(*boilerplate_tasks)
        )

        instruction_indices: list[int] = []
        for operator_line, result in zip(operator_lines, operator_results):
            if result.decision:
                instruction_indices.append(operator_line.index)

        boilerplate_indices: set[int] = set()
        for non_operator_line, result in zip(non_operator_lines, boilerplate_results):
            if result.decision:
                boilerplate_indices.add(non_operator_line.index)

        return instruction_indices, boilerplate_indices

    def _create_overview_chunk(
        self,
        transcript_lines: list[TranscriptLine],
        first_instruction_idx: int,
        boilerplate_indices: set[int],
    ) -> dict | None:
        """Create overview chunk from lines before first Q&A instruction."""
        overview_lines: list[TranscriptLine] = [
            line
            for line in transcript_lines
            if line.index < first_instruction_idx
            and not line.is_operator
            and line.index not in boilerplate_indices
        ]

        if not overview_lines:
            return None

        overview_text: str = "\n".join(
            [f"{line.speaker}: {line.text}" for line in overview_lines]
        )

        return {
            "type": "overview",
            "text": overview_text,
            "line_range": (overview_lines[0].index, overview_lines[-1].index),
        }

    def _create_qa_chunks(
        self,
        transcript_lines: list[TranscriptLine],
        instruction_indices: list[int],
        boilerplate_indices: set[int],
    ) -> list[dict]:
        """Create Q&A chunks from lines between instruction markers."""
        chunks: list[dict] = []

        for i in range(len(instruction_indices)):
            start_idx: int = instruction_indices[i]
            end_idx: int = (
                instruction_indices[i + 1]
                if i + 1 < len(instruction_indices)
                else transcript_lines[-1].index + 1
            )

            qa_lines: list[TranscriptLine] = [
                line
                for line in transcript_lines
                if start_idx < line.index < end_idx
                and line.index not in boilerplate_indices
            ]

            if qa_lines:
                qa_text: str = "\n".join(
                    [f"{line.speaker}: {line.text}" for line in qa_lines]
                )
                chunks.append(
                    {
                        "type": "qa",
                        "text": qa_text,
                        "question_number": i + 1,
                        "line_range": (qa_lines[0].index, qa_lines[-1].index),
                    }
                )

        return chunks

    async def parse(self) -> ParsedOutput:
        """Parse transcript into overview and Q&A chunks."""
        lines: list[str] = self.text.split("\n")
        transcript_lines: list[TranscriptLine] = []

        idx: int
        line: str
        for idx, line in enumerate(lines):
            parsed_line: TranscriptLine | None = self._parse_line(idx, line)
            if parsed_line:
                transcript_lines.append(parsed_line)

        instruction_indices: list[int]
        boilerplate_indices: set[int]
        instruction_indices, boilerplate_indices = await self._identify_special_lines(
            transcript_lines
        )

        chunks: list[dict] = []
        metadata: dict = {
            "total_lines": len(transcript_lines),
            "operator_lines": sum(1 for line in transcript_lines if line.is_operator),
            "instruction_lines": len(instruction_indices),
            "boilerplate_lines": len(boilerplate_indices),
        }

        if not instruction_indices:
            overview_lines: list[TranscriptLine] = [
                line
                for line in transcript_lines
                if line.index not in boilerplate_indices
            ]
            overview_text: str = "\n".join(
                [f"{line.speaker}: {line.text}" for line in overview_lines]
            )
            chunks.append(
                {
                    "type": "overview",
                    "text": overview_text,
                    "line_range": (0, len(transcript_lines) - 1),
                }
            )
            return ParsedOutput(chunks=chunks, metadata=metadata)

        overview_chunk: dict | None = self._create_overview_chunk(
            transcript_lines, instruction_indices[0], boilerplate_indices
        )
        if overview_chunk:
            chunks.append(overview_chunk)

        qa_chunks: list[dict] = self._create_qa_chunks(
            transcript_lines, instruction_indices, boilerplate_indices
        )
        chunks.extend(qa_chunks)

        return ParsedOutput(chunks=chunks, metadata=metadata)
