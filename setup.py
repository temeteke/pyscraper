from setuptools import setup, find_packages

setup(
    name="pyscraper",
    author="temeteke",
    author_email="temeteke@gmail.com",
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    packages=find_packages(),
    install_requires = [
        'requests',
        'selenium',
        'lxml',
    ],
)
