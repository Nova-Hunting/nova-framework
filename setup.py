from setuptools import setup, find_packages

# Core dependencies - minimal for basic functionality (keywords, basic parsing)
# Using ~= (compatible release) to allow patch updates but prevent breaking changes
core_requirements = [
    "requests~=2.31.0",
    "pyyaml~=6.0.1",
    "colorama~=0.4.6"
]

# Advanced LLM dependencies - for semantic matching and LLM evaluation
llm_requirements = [
    "sentence-transformers~=2.3.1",
    "transformers~=4.36.2",
    "openai~=1.12.0",
    "anthropic~=0.18.1"
]

# Development dependencies - for testing and development
dev_requirements = [
    "pytest~=7.4.4",
    "pytest-cov~=4.1.0"
]

# Documentation dependencies - for building documentation
docs_requirements = [
    "mkdocs~=1.5.3",
    "mkdocs-material~=9.5.9"
]

setup(
    name='nova-hunting',
    version='0.2.0',  # Breaking change: rules moved to separate nova-rules repository
    author='Thomas Roccia',
    author_email='contact@securitybreak.io',
    description='Prompt Pattern Matching Framework for Generative AI',
    long_description=open('README.md', encoding='utf-8').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/Nova-Hunting/nova-framework',
    packages=find_packages(exclude=["tests*", "nova_doc*", "*.pyc"]),
    install_requires=core_requirements,
    extras_require={
        'llm': llm_requirements,
        'dev': dev_requirements + llm_requirements,  # Dev includes LLM for testing
        'docs': docs_requirements,
        'all': llm_requirements + dev_requirements + docs_requirements
    },
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'novarun=nova.novarun:main',
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.8',
    license='MIT',
    zip_safe=False,  # This helps ensure all files are properly installed
)
