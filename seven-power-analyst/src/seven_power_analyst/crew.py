from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

# If you want to run a snippet of code before or after the crew starts, 
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators

@CrewBase
class SevenPowerAnalyst():
	"""SevenPowerAnalyst crew"""

	# Learn more about YAML configuration files here:
	# Agents: https://docs.crewai.com/concepts/agents#yaml-configuration-recommended
	# Tasks: https://docs.crewai.com/concepts/tasks#yaml-configuration-recommended
	agents_config = 'config/agents.yaml'
	tasks_config = 'config/tasks.yaml'

	# If you would like to add tools to your agents, you can learn more about it here:
	# https://docs.crewai.com/concepts/agents#agent-tools
	@agent
	def company_analyst(self) -> Agent:
		return Agent(
			config=self.agents_config['company_analyst'],
			verbose=True
		)

	@agent
	def company_analyst_critic(self) -> Agent:
		return Agent(
			config=self.agents_config['company_analyst_critic'],
			verbose=True
		)

	# To learn more about structured task outputs, 
	# task dependencies, and task callbacks, check out the documentation:
	# https://docs.crewai.com/concepts/tasks#overview-of-a-task
	@task
	def initial_company_analysis_task(self) -> Task:
		return Task(
			config=self.tasks_config['company_analysis_task'],
			description="Conduct initial comprehensive analysis of the company following the provided framework.",
			output_file='output/initial_report.md'
		)

	@task
	def company_analysis_critique_task(self) -> Task:
		return Task(
			config=self.tasks_config['company_analysis_critique_task'],
			input_files=['output/initial_report.md'],
			output_file='output/critique.md'
		)

	@task
	def final_company_analysis_task(self) -> Task:
		return Task(
			config=self.tasks_config['company_analysis_task'],
			description="Revise and enhance the initial analysis based on the critique provided.",
			input_files=['output/initial_report.md', 'output/critique.md'],
			output_file='output/final_report.md'
		)

	@crew
	def crew(self) -> Crew:
		"""Creates the SevenPowerAnalyst crew"""
		# To learn how to add knowledge sources to your crew, check out the documentation:
		# https://docs.crewai.com/concepts/knowledge#what-is-knowledge

		return Crew(
			agents=self.agents, # Automatically created by the @agent decorator
			tasks=self.tasks, # Automatically created by the @task decorator
			process=Process.sequential,
			verbose=True,
			# process=Process.hierarchical, # In case you wanna use that instead https://docs.crewai.com/how-to/Hierarchical/
		)
