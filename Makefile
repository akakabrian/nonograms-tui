.PHONY: all bootstrap venv run test test-only clean

VENDOR := vendor/nonogram-db

all: bootstrap venv

bootstrap: $(VENDOR)/.git
$(VENDOR)/.git:
	@echo "==> fetching mikix/nonogram-db into vendor/ (GPL-3.0 puzzle DB)"
	@mkdir -p vendor
	git clone --depth=1 https://github.com/mikix/nonogram-db.git $(VENDOR)

venv: .venv/bin/python
.venv/bin/python:
	python3 -m venv .venv
	.venv/bin/pip install -e .

run: venv
	.venv/bin/python nonograms.py

test: venv
	.venv/bin/python -m tests.qa

test-only: venv
	.venv/bin/python -m tests.qa $(PAT)

test-solver: venv
	.venv/bin/python -m tests.solver_test

clean:
	rm -rf .venv **/__pycache__
