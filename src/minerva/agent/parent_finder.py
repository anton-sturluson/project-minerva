"""Agent for finding parent sections in knowledge hierarchy."""

from pathlib import Path

from pydantic import BaseModel, Field

from minerva.api.gemini import GeminiClient

# TODO: These modules were deleted. Need to update this file to use new architecture:
# - minerva.kb.model.Section no longer exists (use minerva.core.node.SourceNode or create new Section model)
# - minerva.primitive.Agent no longer exists (refactor to use BaseLLMClient directly)
# from minerva.kb.model import Section
# from minerva.primitive import Agent


class ParentDecision(BaseModel):
    """Decision for parent section placement."""

    reasoning: str = Field(description="Brief explanation of the decision")
    parent_section_id: str | None = Field(
        description="Section ID of best parent, or null for top-level"
    )


class ParentFinderAgent:
    """
    Agent that determines the best parent section for a new section.

    TODO: This class needs to be refactored to work with the new architecture.
    Currently disabled due to deleted dependencies (Section, Agent).
    """

    def __init__(self):
        self.llm: GeminiClient = GeminiClient(model="gemini-2.5-flash")
        self.prompt_path: Path = Path(__file__).parent / "find_parent.txt"

    # TODO: Restore this method after refactoring to use new architecture
    # async def afind_parent(
    #     self, header: str, content: str, existing_sections: list[Section]
    # ) -> str | None:
    #     """Find the best parent section for a new section, or None for top-level."""
    #     if not existing_sections:
    #         return None
    #
    #     candidates_text: str = "\n".join(
    #         [
    #             f"- ID: {s.section_id}, Header: {s.header}, Level: {s.level}"
    #             for s in existing_sections
    #         ]
    #     )
    #
    #     user_prompt: str = f"""New Section:
    # Header: {header}
    # Content: {content}
    #
    # Existing Sections:
    # {candidates_text}
    #
    # Determine the best parent section or null for top-level."""
    #
    #     agent: Agent = Agent(
    #         client=self.llm,
    #         prompt_path=self.prompt_path,
    #         prompt=user_prompt,
    #     )
    #
    #     response = await agent.acall(response_schema=ParentDecision)
    #     decision: ParentDecision = response.parsed_object
    #     return decision.parent_section_id

    async def aclose(self) -> None:
        """Close LLM client connections."""
        await self.llm.aclose()
