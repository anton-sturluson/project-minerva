"""Earnings digest crew."""

from pathlib import Path

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

# If you want to run a snippet of code before or after the crew starts,
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators


@CrewBase
class EarningsDigest:
    """EarningsDigest crew"""

    # Learn more about YAML configuration files here:
    # Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
    # Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    def __init__(self, output_dir: Path, ticker: str):
        self.output_dir = output_dir
        self.ticker = ticker

    # If you would like to add tools to your agents, you can learn more about it here:
    # https://docs.crewai.com/concepts/agents#agent-tools
    @agent
    def digest_writer(self) -> Agent:
        return Agent(config=self.agents_config["digest_writer"], verbose=True)

    @agent
    def financial_expert(self) -> Agent:
        return Agent(config=self.agents_config["financial_expert"], verbose=True)

    @task
    def financial_extraction_task(self) -> Task:
        return Task(
            config=self.tasks_config["financial_extraction_task"],
            output_file=str(self.output_dir / f"{self.ticker}_financial_extraction.md"),
        )

    # To learn more about structured task outputs,
    # task dependencies, and task callbacks, check out the documentation:
    # https://docs.crewai.com/concepts/tasks#overview-of-a-task
    @task
    def earnings_call_digest_task(self) -> Task:
        return Task(
            config=self.tasks_config["earnings_call_digest_task"],
            output_file=str(self.output_dir / f"{self.ticker}_earnings_call_digest.md"),
        )

    @crew
    def crew(self) -> Crew:
        """Creates the EarningsDigest crew"""
        # To learn how to add knowledge sources to your crew, check out the documentation:
        # https://docs.crewai.com/concepts/knowledge#what-is-knowledge

        return Crew(
            agents=self.agents,  # Automatically created by the @agent decorator
            tasks=self.tasks,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
        )
