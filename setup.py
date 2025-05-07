# setup.py
import setuptools
import os

# Function to read the README file for the long description
def read(fname):
    try:
        return open(os.path.join(os.path.dirname(__file__), fname), encoding='utf-8').read()
    except IOError:
        return "" # Return empty string if README is not found

setuptools.setup(
    name="pyper-sdk",  # How users will pip install it (e.g., piper-sdk)
    version="0.1.0",  # Start with an initial version
    author="Piper", # CHANGE THIS
    author_email="devs@agentpiper.com", # CHANGE THIS
    description="Python SDK for Piper Agent Credential Management",
    long_description=read('README.md'), # Reads the README file
    long_description_content_type="text/markdown", # Format of the README
    url="https://github.com/greylab0/piper-python-sdk", # CHANGE THIS LATER
    # Automatically find the piper_sdk package
    packages=setuptools.find_packages(where=".", include=['piper_sdk*']),
    # If your code was in a 'src' directory, uncomment and adjust below:
    # package_dir={'': 'src'},
    # packages=setuptools.find_packages(where='src'),

    # List of dependencies needed by your SDK
    install_requires=[
        "requests>=2.20.0", # Dependency for making HTTP calls
    ],
    # Minimum Python version supported
    python_requires='>=3.7',
    # Standard classifiers to help users find your package
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License", # Or choose another license like Apache-2.0
        "Operating System :: OS Independent",
        "Development Status :: 3 - Alpha", # Current status
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Security",
    ],
    keywords='piper credentials secrets sdk agent gcp sts', # Add relevant keywords
    project_urls={ # Optional: Add relevant links
        'Documentation': 'https://github.com/greylab0/piper-python-sdk/blob/main/README.md',
        'Source': 'https://github.com/greylab0/piper-python-sdk',
        'Tracker': 'https://github.com/greylab0/piper-python-sdk/issues',
    },
)