#!/usr/bin/env make
include Makehelp

## Run linters & tests

lint:
	flake8
	yamllint --strict --format colored .
	@echo '*** linters are happy ***'
.PHONY: lint

test: lint
	PYTHONPATH=./src pytest --cov=src --cov-report term-missing
	@echo '*** tests are happy ***'
.PHONY: test
