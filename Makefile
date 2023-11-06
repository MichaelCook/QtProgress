.PHONY: check-py
check-py: App.py.check-py~
-include App.py.dep-py~

App.py.check-py~: App.py
	check-py App.py . ../../lib

MainWindow.py: MainWindow.ui
	uses pyuic5
	pyuic5 MainWindow.ui -o MainWindow.py
