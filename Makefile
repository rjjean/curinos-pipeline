# Curinos validation pipeline — single-command orchestration.
#
# Usage:
#   make all       # full pipeline: install, browsers, run, report
#   make run       # just run the pipeline (assumes deps installed)
#   make setup     # install Python deps + Playwright Chromium + k6
#   make clean     # wipe reports/
#
# Prerequisites:
#   - Python 3.12+ with a virtual environment activated:
#       python3.12 -m venv .venv && source .venv/bin/activate
#   - sudo access (for installing k6 system package on first run)

.PHONY: all setup setup-python setup-k6 run report clean help

PY := python3
PIP_FLAGS := --quiet

help:
	@echo "Targets: all, setup, run, report, clean"

all: setup run

setup: setup-python setup-k6

setup-python:
	@echo "[make] Installing Python dependencies ..."
	$(PY) -m pip install $(PIP_FLAGS) -r requirements.txt
	@echo "[make] Installing Playwright Chromium ..."
	$(PY) -m playwright install --with-deps chromium

setup-k6:
	@if command -v k6 >/dev/null 2>&1; then \
		echo "[make] k6 already installed ($$(k6 version | head -1))"; \
	else \
		echo "[make] Installing k6 ..."; \
		curl -fsSL https://dl.k6.io/key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/k6-archive-keyring.gpg; \
		echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list; \
		sudo apt update; \
		sudo apt install -y k6; \
	fi

run:
	@mkdir -p reports
	@PYTHONPATH=. $(PY) -m orchestrator.run_pipeline

report:
	@cat reports/report.md 2>/dev/null || echo "No report yet — run 'make run' first."

clean:
	rm -rf reports/*
	@echo "[make] Cleaned reports/"