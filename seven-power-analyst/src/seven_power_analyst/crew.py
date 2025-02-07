from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task

# If you want to run a snippet of code before or after the crew starts, 
# you can use the @before_kickoff and @after_kickoff decorators
# https://docs.crewai.com/concepts/crews#example-crew-class-with-decorators
crew_llm = LLM(model="gpt-4o-mini", temperature=0.5)
manager_llm = LLM(model="gpt-4o", temperature=0.5)

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
			llm=crew_llm,
			verbose=True
		)

	@agent
	def company_analyst_critic(self) -> Agent:
		return Agent(
			config=self.agents_config['company_analyst_critic'],
			llm=crew_llm,
			verbose=True
		)

	@agent
	def hamilton_helmer(self) -> Agent:
		return Agent(
			config=self.agents_config['hamilton_helmer'],
			llm=manager_llm,
			verbose=True
		)

	@agent
	def sector_analyst(self) -> Agent:
		return Agent(
			config=self.agents_config['sector_analyst'],
			llm=crew_llm,
			verbose=True
		)

	# To learn more about structured task outputs, 
	# task dependencies, and task callbacks, check out the documentation:
	# https://docs.crewai.com/concepts/tasks#overview-of-a-task
	# @task
	# def initial_company_analysis_task(self) -> Task:
	# 	return Task(
	# 		config=self.tasks_config['company_analysis_task'],
	# 		output_file='output/initial_report.md'
	# 	)

	# @task
	# def company_analysis_critique_task(self) -> Task:
	# 	return Task(
	# 		config=self.tasks_config['company_analysis_critique_task'],
	# 		input_files=['output/initial_report.md'],
	# 		output_file='output/critique.md'
	# 	)

	# @task
	# def sector_analysis_task(self) -> Task:
	# 	return Task(
	# 		config=self.tasks_config['sector_analysis_task'],
	# 		output_file='output/sector_analysis.md'
	# 	)

	@task
	def final_company_analysis_task(self) -> Task:
		return Task(
			config=self.tasks_config['seven_power_analysis_task'],
			# input_files=['output/initial_report.md', 'output/critique.md', 'output/sector_analysis.md'],
			output_file='output/final_report.md'
		)

	@crew
	def crew(self) -> Crew:
		"""Creates the SevenPowerAnalyst crew"""
		# To learn how to add knowledge sources to your crew, check out the documentation:
		# https://docs.crewai.com/concepts/knowledge#what-is-knowledge

		return Crew(
			agents=self.agents,
			tasks=self.tasks,
			process=Process.sequential,
			verbose=True,
		)
