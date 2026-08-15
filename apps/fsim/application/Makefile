PYTHON := .venv/bin/python

.PHONY: client corpus soup-to-nuts test

client:
	$(PYTHON) -B scripts/build_regular_lod_manager_survey.py
	$(PYTHON) -B scripts/build_agondev_regular_policy.py
	$(PYTHON) -B scripts/build_regular_lod_c_policy_survey.py --skip-module-build --policy-mode c-guarded

corpus:
	$(PYTHON) -B scripts/build_regional_hex_terrain.py --selection full
	$(PYTHON) -B scripts/build_regular_lod_corpus.py

soup-to-nuts: corpus client

test:
	$(PYTHON) -B -m unittest discover -s tests -v
