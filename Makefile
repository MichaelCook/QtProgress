include ../../lib/config.mk

ifdef HAVE_PYTHON_MODULE_PyQt5
all: check-py
endif

.PHONY: check-py
check-py: .App.py.${CHECK_PY_STAMP}
-include .App.py.dep-py~

.App.py.${CHECK_PY_STAMP}: App.py
	${QUIET}echo Check App.py
	${QUIET}${SHOW_IF_FAIL} check-py $@ .App.py.dep-py~ App.py . ../../lib

all: MainWindow.py
MainWindow.py: MainWindow.ui
	${QUIET}echo Generate $@
	${QUIET}uses pyuic5
	${QUIET}pyuic5 MainWindow.ui -o MainWindow.py

# Gracefully handle *.py files that have been removed
# but still appear in the *.dep-py~ files
%.py:
	${QUIET}echo No file $@
