from setuptools import setup, find_packages

PACKAGE_NAME = 'python-ecobee'

PACKAGES = find_packages(exclude=['tests', 'tests.*', 'python'])

REQUIRES = [
    'requests>=2,<3',
]

setup(
    name=PACKAGE_NAME,
    version='1.0.0',
    license='MIT License',
    author='Micahel Stella',
    author_email='michael@thismetalsky.org',
    description='Library to talk to an Ecobee thermostat',
    packages=PACKAGES,
    include_package_data=True,
    zip_safe=False,
    platforms='any',
    install_requires=REQUIRES,
    keywords=['home', 'automation'],
    classifiers=[
        'Intended Audience :: End Users/Desktop',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.4',
        'Topic :: Home Automation'
    ]
)
