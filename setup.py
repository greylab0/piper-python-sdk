import setuptools

setuptools.setup(
    name="pyper-sdk",  # The pip install name
    version="0.7.1",
    author="Piper",
    author_email="devs@agentpiper.com",
    description="Python SDK for Piper Agent Credential Management. Secure, flexible, and simple.",
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    url="https://github.com/greylab0/piper-python-sdk",
    
    packages=setuptools.find_packages(where=".", include=['piper_sdk*']),

    install_requires=[
        "requests>=2.20.0",
        # "keyring>=23.0.0", # Currently not supported
    ],
    python_requires='>=3.7',
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
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