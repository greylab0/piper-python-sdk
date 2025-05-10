import setuptools

setuptools.setup(
    name="pyper-sdk",  # The pip install name
    version="0.3.1",
    author="Piper",
    author_email="devs@agentpiper.com",
    description="Python SDK for Piper Agent Credential Management with environment fallback.", # Update description
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    url="https://github.com/greylab0/piper-python-sdk", # Your GitHub repo
    
    # This line tells setuptools to find the 'piper_sdk' directory
    # and package it as the 'piper_sdk' module.
    packages=setuptools.find_packages(where=".", include=['piper_sdk*']),
    # If you only have one top-level package, you can also do:
    # packages=['piper_sdk'], 

    install_requires=[
        "requests>=2.20.0",
        # "keyring>=23.0.0", # Only if SDK directly uses keyring, currently it doesn't
    ],
    python_requires='>=3.7',
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License", # Or your chosen SPDX identifier
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta", # Updated status
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Security",
    ],
    keywords='piper credentials secrets sdk agent gcp sts mcp llm api key',
    project_urls={
        'Documentation': 'https://github.com/greylab0/piper-python-sdk/blob/main/README.md',
        'Source': 'https://github.com/greylab0/piper-python-sdk',
        'Tracker': 'https://github.com/greylab0/piper-python-sdk/issues',
    },
)