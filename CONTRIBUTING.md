# Contributing

We welcome contributions to squawk-pre-commit. Here's how to get started.

## Development Setup

1. Clone the repo and install dependencies:

```bash
git clone https://github.com/kintsugi-tax/squawk-pre-commit.git
cd squawk-pre-commit
poetry install
```

2. Install pre-commit hooks:

```bash
pre-commit install
```

3. Run the test suite:

```bash
poetry run pytest tests/ -v
```

## Submitting Changes

1. Fork the repo and create a branch from `main`
2. Make your changes and add tests where appropriate
3. Ensure all tests pass and pre-commit hooks are clean
4. Open a pull request against `main`

## Reporting Issues

Open an issue on [GitHub](https://github.com/kintsugi-tax/squawk-pre-commit/issues) with a clear description of the problem and steps to reproduce.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
