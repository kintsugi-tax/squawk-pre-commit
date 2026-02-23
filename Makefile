.PHONY: setup_pre_commit run_pre-commit run_unit_tests run_ruff run_pyrefly clean help

# This trick comes from https://marmelab.com/blog/2016/02/29/auto-documented-makefile.html
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

setup_pre_commit: ## Setup pre-commit hooks
	@poetry run pre-commit install

run_pre-commit: ## Run pre-commit hooks
	@poetry run pre-commit run --all-files

run_unit_tests: ## Run unit tests
	@poetry run pytest tests/ -v

run_ruff: ## Run ruff, the Python linter and code formatter
	@poetry run ruff check . --fix
	@poetry run ruff format .

run_pyrefly: ## Run pyrefly, a static type checker for Python
	@poetry run pyrefly check

clean: ## Clean up the project (e.g., remove cache files)
	@find . -type f -name '*.pyc' -delete
	@find . -type d -name '__pycache__' -delete
