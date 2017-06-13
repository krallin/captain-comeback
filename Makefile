release: clean
	python setup.py sdist upload
	python setup.py bdist_wheel upload

dist: clean
	python setup.py sdist
	python setup.py bdist_wheel
	ls -l dist

install: clean
	python setup.py install

clean: clean-tox clean-build clean-pyc

clean-build:
	rm -fr build/
	rm -fr dist/
	rm -fr *.egg-info

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +

clean-tox:
	rm -rf .tox/

integration/hog: integration/hog.c
	gcc integration/hog.c -Wl,--no-export-dynamic -static -o integration/hog

noswap:
	integration/noswap.sh

unit: integration/hog noswap
	python setup.py nosetests

integration: install integration/hog noswap
	integration/test.sh
	integration/ignore.sh
	integration/restart.sh
	integration/docker-term-all.sh
	integration/errors.sh
	integration/wipe.sh
	integration/stopped.sh

test: unit integration

.PHONY: release dist install clean-tox clean-pyc clean-build test noswap unit integration
