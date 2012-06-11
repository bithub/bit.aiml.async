from setuptools import setup, find_packages
import os

version = '0.0.9'

setup(name='bit.aiml.async',
      version=version,
      description="Bit AIML async",
      long_description=open("README.txt").read() + "\n" +
                       open(os.path.join("docs", "HISTORY.txt")).read(),
      classifiers=[
        "Programming Language :: Python",
        "Topic :: Software Development :: Libraries :: Python Modules",
        ],
      keywords='',
      author='Ryan Northey',
      author_email='ryan@3ca.org.uk',
      url='http://code.3ca.org.uk',
      license='GPL',
      packages=find_packages(exclude=['ez_setup']),
      namespace_packages=['bit', 'bit.aiml'],
      include_package_data=True,
      zip_safe=False,
      install_requires=[
          'setuptools',
          'zope.event',
          'zope.interface',
          'zope.component',
          'zope.i18nmessageid',
          'twisted',
          'bit.bot.base',
      ],
      entry_points="""
      # -*- Entry points: -*-
      """,
      )
