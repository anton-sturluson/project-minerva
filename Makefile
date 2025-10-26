.PHONY: lint

lint:
	@echo "Running ruff check..."
	docker run --rm -v $(PWD):/app -w /app ghcr.io/astral-sh/ruff:0.12.0 check --fix src/
	@echo "Running ruff format check..."
	docker run --rm -v $(PWD):/app -w /app ghcr.io/astral-sh/ruff:0.12.0 format src/
	@echo "Linting complete!"

