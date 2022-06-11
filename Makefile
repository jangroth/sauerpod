#!/usr/bin/env make
include Makehelp


## Run linters
lint:
	flake8
	yamllint --strict --format colored .
	@echo '*** linters are happy ***'
.PHONY: lint

## Run tests
test: lint
	PYTHONPATH=./src pytest --ignore=cdk.out --cov=src --cov-report term-missing
	@echo '*** tests are happy ***'
.PHONY: test
