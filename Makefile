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
SQL_SOURCES = $(shell find infra pipelines -name '*.sql' -not -path '*/target/*' 2>/dev/null)
# The bindings build and run in a throwaway environment, outside the workspace lock.
ENGINE_PYTHON := uv run --no-project --managed-python --python 3.12 --reinstall-package btcore \
	--with ./engine --with "numpy>=2,<3" --with "pytest>=8.3"

.DEFAULT_GOAL := ci
.PHONY: setup lint test-engine bench-engine test-python test-contracts test-dbt test-web ci up down migrate seed backfill bootstrap sync pgadmin

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
	@if grep -rnE 'nanobind|Python\.h|pybind11' engine/src engine/include; then \
		echo "engine library references Python"; exit 1; \
	fi
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
# A sanitizer runtime must be loaded before the interpreter starts, so only the default build runs
# the bindings.
ifeq ($(SANITIZER),)
	$(ENGINE_PYTHON) pytest engine/tests/python
endif

# Runs the engine's benchmarks in the default build; BENCH_ARGS passes Google Benchmark's flags.
bench-engine:
	cd engine && cmake --preset default
	cd engine && cmake --build --preset default --target btcore_benchmarks
	build/engine/tests/btcore_benchmarks $(BENCH_ARGS)

test-python:
	uv run pytest

test-contracts:
	uv run pytest -m contract

test-dbt:
	cd pipelines/dbt && uv run dbt parse --profiles-dir .
	cd pipelines/dbt && uv run dbt build --profiles-dir . --target fixture

test-web:
	npm --prefix web run typecheck
	npm --prefix web run test

ci: lint test-engine test-python test-dbt test-web

up:
	docker compose up -d --build --wait

down:
	docker compose down

# Serves pgAdmin on PGADMIN_PORT, defaulting to 5050, with this stack's Postgres registered.
pgadmin:
	docker compose --profile pgadmin up -d pgadmin --wait

migrate:
	uv run alembic -c pipelines/alembic.ini upgrade head

seed:
	uv run python scripts/load_fixture_seed.py

# Runs a flow against the database .env names, printed before the flow starts. FLOW_ARGS carries a
# range, FLOW_ARGS="--from DAY --to DAY", or a sync's last day, FLOW_ARGS="--day DAY".
bootstrap:
	uv run --env-file .env python -m pipelines.flows bootstrap $(FLOW_ARGS)

sync:
	uv run --env-file .env python -m pipelines.flows sync $(FLOW_ARGS)

# Downloads every bhavcopy both venues have published into the cache, throttled, and stores nothing
# in the database. A day already cached costs no request. The default start is the first day either
# venue names its instruments by ISIN; a venue skips the days before its own.
BACKFILL_FROM ?= 2011-06-22
BACKFILL_TO ?= $(shell date +%Y-%m-%d)

backfill:
	uv run python scripts/build_fixture_dataset.py download \
		--start $(BACKFILL_FROM) --end $(BACKFILL_TO)
