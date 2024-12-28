.PHONY: test
test:
	PYTHONPATH=src pytest --log-cli-level=INFO -sv
