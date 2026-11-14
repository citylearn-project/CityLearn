import os
import re
import setuptools

ROOT = os.path.dirname(__file__)
VERSION_RE = re.compile(r"__version__\s*=\s*['\"]([\w\.-]+)['\"]")
with open(os.path.join(ROOT, 'README.md'), 'r', encoding='utf-8') as fh:
    long_description = fh.read()

with open(os.path.join(ROOT, 'requirements.txt'), 'r', encoding='utf-8') as fh:
    requirements = fh.readlines()
    requirements = [requirement.strip().replace('\n', '').replace('\r', '') for requirement in requirements]
    requirements = [requirement for requirement in requirements if len(requirement) != 0 and requirement[0] != '#']


def get_version():
    with open(os.path.join(ROOT, 'citylearn', '__init__.py'), 'r', encoding='utf-8') as fh:
        init = fh.read()
    return VERSION_RE.search(init).group(1)

setuptools.setup(
    name='citylearn',
    version=get_version(),
    author='Soft-CPS Research Group, Jose Ramon Vazquez-Canteli, Kingsley Nweye, Zoltan Nagy',
    author_email='jose@isep.ipp.pt',
    maintainer='Tiago Fonseca',
    maintainer_email='calof@isep.ipp.pt',
    description=(
        'CityLearn: an energy-community reinforcement-learning environment focused on EV/BESS/PV, '
        'electrical-service constraints, dynamic topology and community-market experimentation.'),
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/citylearn-project/CityLearn',
    license='MIT',
    packages=setuptools.find_packages(),
    include_package_data=True,
    install_requires=requirements,
    extras_require={
        'parquet': ['pyarrow'],
        'pysam': ['nrel-pysam'],
        # Only citylearn.end_use_load_profiles (building new datasets from EULP/EnergyPlus) needs these.
        'end_use_load_profiles': ['doe_xstock>=2.0.0', 'openstudio<=3.10.0', 'eppy'],
        'all': ['pyarrow', 'nrel-pysam'],
    },
    entry_points={'console_scripts': ['citylearn = citylearn.__main__:main']},
    project_urls={
        'Source': 'https://github.com/citylearn-project/CityLearn',
        'Documentation': 'https://www.citylearn.net/',
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.9',
)
