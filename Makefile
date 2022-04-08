.PHONY: check-py
check-py:
	python3 -m mypy --strict --no-error-summary *.py ../../lib/mcook.py
	python3 -m flake8 --config ~/.config/flake8 *.py
