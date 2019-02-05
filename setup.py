#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from __future__ import absolute_import, print_function

from glob import glob
from os.path import basename, dirname, join, splitext
from setuptools import find_packages, setup
import io
import re
import sys

import versioneer

# See https://blog.ionelmc.ro/2014/06/25/python-packaging-pitfalls/
setup(name='dropbot-chip-qc',
      version=versioneer.get_version(),
      cmdclass=versioneer.get_cmdclass(),
      description='Quality control tools for testing DropBot digital microfluidic chips.',
      keywords='',
      author='Christian Fobel',
      author_email='christian@fobel.net',
      url='https://github.com/sci-bots/dropbot-chip-qc',
      license='BSD',
      packages=find_packages('src'),
      package_dir={'': 'src'},
      install_requires=[],
      py_modules=[splitext(basename(path))[0] for path in glob('src/*.py')],
      # Install data listed in `MANIFEST.in`
      include_package_data=True)
