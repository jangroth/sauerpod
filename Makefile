#!/usr/bin/env make
include Makehelp

## Run linters & tests
test:
	flake8
	yamllint -f parsable .
	PYTHONPATH=./src pytest --cov=src --cov-report term-missing
	@echo '*** all checks passing ***'
.PHONY: test
