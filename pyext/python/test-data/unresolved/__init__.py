try:
    import notfound0
except ImportError:
    pass

try:
    from notfound1 import notfound2
except ImportError:
    pass

try:
    import unresolved.notfound3
except ImportError:
    pass

try:
    import unresolved.notfound3.notfound4
except ModuleNotFoundError:
    pass

try:
    from unresolved import notfound5
except ImportError:
    pass

try:
    from unresolved.notfound6 import notfound7
except ImportError:
    pass

try:
    from . import notfound8
except ImportError:
    pass

try:
    from .notfound9 import notfound10
except ImportError:
    pass
