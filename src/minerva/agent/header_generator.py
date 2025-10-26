"""Agent for generating section headers from knowledge pieces."""

from pathlib import Path

from pydantic import BaseModel, Field

from minerva.api.gemini import GeminiClient

# TODO: This module was deleted. Need to refactor to use BaseLLMClient directly
# from minerva.primitive import Agent


class SectionHeader(BaseModel):
    """Generated section header."""

    header: str = Field(description="Concise, generalizable section header (2-6 words)")


class HeaderGeneratorAgent:
    """
    Agent that generates appropriate section headers for knowledge pieces.

    TODO: This class needs to be refactored to work with the new architecture.
    Currently disabled due to deleted dependency (Agent).
    """

    def __init__(self):
        self.llm: GeminiClient = GeminiClient(model="gemini-2.5-flash")
        self.prompt_path: Path = Path(__file__).parent / "generate_header.txt"

    # TODO: Restore this method after refactoring to use BaseLLMClient directly
    # async def agenerate(self, knowledge: str) -> str:
    #     """Generate a section header for a knowledge piece."""
    #     agent: Agent = Agent(
    #         client=self.llm,
    #         prompt_path=self.prompt_path,
    #         prompt=f"Knowledge: {knowledge}",
    #     )
    #
    #     response = await agent.acall(response_schema=SectionHeader)
    #     header_obj: SectionHeader = response.parsed_object
    #     return header_obj.header

    async def aclose(self) -> None:
        """Close LLM client connections."""
        await self.llm.aclose()
