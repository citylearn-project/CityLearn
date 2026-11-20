"""Errors that name the installation command of a missing optional dependency."""

TORCH_CPU_INSTALL = 'pip install torch --index-url https://download.pytorch.org/whl/cpu'


def missing_dependency(feature: str, package: str, extra: str) -> ImportError:
    """Return an ``ImportError`` that tells the user which CityLearn extra provides ``package``."""

    message = (
        f'{feature} needs {package}, which is an optional dependency of CityLearn. '
        f'Install it with: pip install "citylearn[{extra}]"'
    )

    if package == 'PyTorch':
        message += (
            f'. The default PyTorch wheels include several GB of CUDA libraries; for a CPU-only '
            f'PyTorch, run "{TORCH_CPU_INSTALL}" first.'
        )

    return ImportError(message)
