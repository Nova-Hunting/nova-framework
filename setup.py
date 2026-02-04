from setuptools import setup, find_packages

# All dependencies included in standard installation
# Using ~= (compatible release) to allow patch updates but prevent breaking changes
requirements = [
    # Core
    "requests~=2.32.5",
    "pyyaml~=6.0.1",
    "colorama~=0.4.6",
    # LLM/Semantic
    "sentence-transformers~=3.3.1",
    "transformers~=4.47.0",
    "openai~=1.12.0",
    "anthropic~=0.18.1",
    # Testing
    "pytest~=7.4.4",
    "pytest-cov~=4.1.0",
]

setup(
    name='nova-hunting',
    version='0.2.1',
    author='Thomas Roccia',
    author_email='contact@securitybreak.io',
    description='Prompt Pattern Matching Framework for Generative AI',
    long_description=open('README.md', encoding='utf-8').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/Nova-Hunting/nova-framework',
    packages=find_packages(exclude=["tests*", "nova_doc*", "*.pyc"]),
    install_requires=requirements,
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
