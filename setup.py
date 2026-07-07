import re
from pathlib import Path

from setuptools import setup, find_packages

ROOT = Path(__file__).parent


def get_version():
    version_file = ROOT / "nova" / "_version.py"
    match = re.search(r'__version__ = ["\']([^"\']+)["\']', version_file.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError("Unable to determine package version")
    return match.group(1)

# Runtime dependencies included in standard installation.
# Using ~= (compatible release) allows patch updates while avoiding broad major-version drift.
requirements = [
    # Core
    "requests~=2.34.2",
    "colorama~=0.4.6",
]

semantic_requirements = [
    # Current safe semantic stack requires Python 3.10+, matching NOVA's runtime floor.
    "sentence-transformers~=5.5.0; python_version >= '3.10'",
    "transformers~=5.8.1; python_version >= '3.10'",
]

test_requirements = [
    "pytest~=9.0.3",
    "pytest-asyncio~=1.3.0",
    "pytest-cov~=7.1.0",
    "pyyaml~=6.0.3",
]

docs_requirements = [
    "mkdocs~=1.5.3",
    "mkdocs-material~=9.5.9",
]

lint_requirements = [
    "ruff~=0.8.6",
]

security_requirements = [
    "pip-audit~=2.10.0",
]

release_requirements = [
    "build~=1.2.2",
    "twine~=6.2.0",
]

setup(
    name='nova-hunting',
    version=get_version(),
    author='Thomas Roccia',
    author_email='contact@securitybreak.io',
    description='Prompt Pattern Matching Framework for Generative AI',
    long_description=(ROOT / 'README.md').read_text(encoding='utf-8'),
    long_description_content_type='text/markdown',
    url='https://github.com/Nova-Hunting/nova-framework',
    project_urls={
        "Source": "https://github.com/Nova-Hunting/nova-framework",
        "Issues": "https://github.com/Nova-Hunting/nova-framework/issues",
        "Security": "https://github.com/Nova-Hunting/nova-framework/security",
        "Changelog": "https://github.com/Nova-Hunting/nova-framework/blob/main/CHANGELOG.md",
        "Production Readiness": "https://github.com/Nova-Hunting/nova-framework/blob/main/PRODUCTION_READINESS.md",
    },
    packages=find_packages(exclude=["tests*", "nova_doc*", "*.pyc"]),
    install_requires=requirements,
    extras_require={
        "test": test_requirements,
        "docs": docs_requirements,
        "lint": lint_requirements,
        "semantic": semantic_requirements,
        "security": security_requirements,
        "release": release_requirements,
        "all": semantic_requirements,
        "dev": test_requirements + docs_requirements + lint_requirements + semantic_requirements + security_requirements + release_requirements,
    },
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'novarun=nova.novarun:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'Topic :: Security',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.10',
    license='MIT',
    zip_safe=False,  # This helps ensure all files are properly installed
)
