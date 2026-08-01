SHELL := /bin/bash

REQUIRE_MODERN_MAKE := $(if $(filter setup,$(MAKECMDGOALS)),,yes)
ifdef REQUIRE_MODERN_MAKE
ifeq ($(firstword $(subst ., ,$(MAKE_VERSION))),3)
$(error GNU Make 4.0 or newer is required, found $(MAKE_VERSION). Run make setup for the fix)
endif
endif

UNAME_S := $(shell uname -s)

VCPKG_ROOT ?= $(HOME)/vcpkg
export VCPKG_ROOT
export SANITIZER

PRESET := $(if $(SANITIZER),sanitizer,default)
PYTHON_SRC := api/src pipelines/src scripts
CPP_SOURCES = $(shell find engine -path engine/build -prune -o \
	\( -name '*.cpp' -o -name '*.hpp' \) -print)
SQL_SOURCES = $(shell find infra pipelines -name '*.sql' 2>/dev/null)

.DEFAULT_GOAL := ci
.PHONY: setup lint test-engine test-python test-dbt test-web ci up down

setup:
ifeq ($(UNAME_S),Darwin)
	brew install cmake ninja ccache make
else
	sudo apt-get update
	sudo apt-get install -y build-essential cmake ninja-build ccache
endif
	@test -d $(VCPKG_ROOT) || git clone https://github.com/microsoft/vcpkg.git $(VCPKG_ROOT)
	$(VCPKG_ROOT)/bootstrap-vcpkg.sh -disableMetrics
	uv sync
	npm --prefix web ci
	uv run pre-commit install --install-hooks
ifeq ($(UNAME_S),Darwin)
	@echo
	@echo "macOS ships GNU Make 3.81 as /usr/bin/make. To make the make command resolve to the"
	@echo "version this repository requires, add the following to your shell profile:"
	@echo
	@echo '  export PATH="$(shell brew --prefix make)/libexec/gnubin:$$PATH"'
	@echo
	@echo "Until then, invoke the targets as gmake."
endif

lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy $(PYTHON_SRC)
	uv run clang-format --dry-run --Werror $(CPP_SOURCES)
	npm --prefix web run lint
	@if [ -n "$(SQL_SOURCES)" ]; then \
		uv run sqlfluff lint $(SQL_SOURCES); \
	else \
		echo "no sql to lint"; \
	fi

test-engine:
	cd engine && cmake --preset $(PRESET)
	cd engine && cmake --build --preset $(PRESET)
	cd engine && ctest --preset $(PRESET)

test-python:
	uv run pytest

test-dbt:
	cd pipelines/dbt && uv run dbt parse --profiles-dir .

test-web:
	npm --prefix web run typecheck
	npm --prefix web run test

ci: lint test-engine test-python test-dbt test-web

up:
	docker compose up -d --build --wait

down:
	docker compose down
