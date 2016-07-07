#!/usr/bin/env python
# coding: utf-8
import os
from setuptools import setup

HERE = os.path.dirname(__file__)

with open(os.path.join(HERE, 'README.md')) as readme_file:
    readme = readme_file.read()

with open(os.path.join(HERE, 'CHANGELOG.md')) as history_file:
    changelog = history_file.read()

requirements = ["linuxfd>=1.0,<2", "psutil>=4.3,<5", "six>=1.0,<2"]
test_requirements = []

setup(
    name='captain_comeback',
    version='0.1.0',
    description="Userland container OOM manager.",
    long_description=readme + '\n\n' + changelog,
    author="Thomas Orozco",
    author_email='thomas@aptible.com',
    url='https://github.com/krallin/captain_comeback',
    packages=[
        'captain_comeback',
        'captain_comeback.restart',
        'captain_comeback.test'
    ],
    include_package_data=True,
    install_requires=requirements,
    license="MIT license",
    zip_safe=False,
    keywords='captain_comeback',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        "Programming Language :: Python :: 2",
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
    test_suite='captain_comeback.test',
    tests_require=test_requirements,
    entry_points={'console_scripts': [
        'captain-comeback = captain_comeback.cli:cli_entrypoint']}
)
