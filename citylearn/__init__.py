__version__ = '3.1.0'

__all__ = ["MultiCommunityEnv", "__version__"]


def __getattr__(name: str):
    if name == "MultiCommunityEnv":
        from citylearn.multi_community import MultiCommunityEnv

        return MultiCommunityEnv

    raise AttributeError(f"module 'citylearn' has no attribute {name!r}")
