MYPY = python3 -m mypy

.PHONY: mypy
mypy:
	$(MYPY) *.py ../../lib/mcook.py
