SHELL := /bin/bash
PYTHON := backend/.venv/bin/python

.PHONY: bootstrap start stop doctor verify test security

bootstrap:
	bash scripts/mac/bootstrap.sh

start:
	bash scripts/mac/start.sh

stop:
	bash scripts/mac/stop.sh

doctor:
	bash scripts/mac/doctor.sh

verify:
	bash scripts/verify.sh

test:
	cd backend && ../$(PYTHON) -m pytest -q

security:
	$(PYTHON) scripts/check_no_secrets.py
	$(PYTHON) scripts/check_rules_contract.py
