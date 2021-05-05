MYPY = python3 -m mypy

.PHONY: mypy
mypy:
	$(MYPY) App ../../lib
