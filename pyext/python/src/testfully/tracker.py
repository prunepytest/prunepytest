import builtins
import importlib
import io
import sys
import traceback
import types
from functools import wraps

from typing import Any, Iterable, Mapping, Optional, Set, Tuple


EMPTY_SET = frozenset()


IGNORED_FRAMES = {
    __file__,
    "<frozen importlib._bootstrap>",
    "<frozen importlib._bootstrap_external>",
}
def omit_tracker_frames(tb: traceback.StackSummary) -> Iterable[traceback.FrameSummary]:
    """
    Remove stack frames associated with the import machinery or our hooking into it.
    This makes it easier to analyze any error that might be reported by the validator
    """
    return (frame for frame in tb if frame.filename not in IGNORED_FRAMES)


def is_validator_frame(frame: traceback.FrameSummary):
    return frame.name == 'import_with_capture' and frame.filename.endswith('validator.py')


def _apply_patch(o: object, attr_name: str, attr_val: Any) -> None:
    p = attr_name.split('.')
    for n in p[:-1]:
        o = getattr(o, n)
    setattr(o, p[-1], attr_val.__call__(getattr(o, p[-1], None)))


def apply_patches(name: str, patches) -> None:
    m = sys.modules[name]
    for attr_name, attr_val in patches[name].items():
        _apply_patch(m, attr_name, attr_val)


def _builtins_import_no_cache(name, globals=None, locals=None, fromlist=(), level=0):
    return importlib.__import__(name, globals, locals, fromlist, level)


# Some relevant documentation:
#   - https://docs.python.org/3/reference/import.html#importsystem
#   - https://docs.python.org/3/reference/simple_stmts.html#import
#   - https://docs.python.org/3/reference/datamodel.html#import-related-attributes-on-module-objects
#   - https://github.com/python/cpython/blob/v3.13.0/Lib/importlib/_bootstrap.py
class Tracker:
    __slots__ = ('stack', 'cxt', 'tracked',
                 'old_find_and_load', 'old_handle_fromlist', 'old_builtins_import',
                 'dynamic', 'dynamic_stack', 'dynamic_imports', 'dynamic_users',
                 'dynamic_anchors', 'dynamic_ignores', 'file_to_module',
                 'log_file', 'prefixes', 'patches')

    def __init__(self):
        self.stack = [""]
        self.cxt = set()
        # map of fully-qualified module name to
        # *full* set of (fully-qualified names of) modules it depends on
        self.tracked = {"": self.cxt}
        # optionally record locations of dynamic imports
        self.dynamic = []
        self.dynamic_stack = 0
        # optional aggregation of dynamic imports into "anchors"
        # this is useful to ensure the validator works reliably even
        # if some dynamic imports are being cached across tests
        self.dynamic_anchors = {}
        self.dynamic_ignores = {}
        # map: (module name, function name) -> set of dynamic imports
        self.dynamic_imports = {}
        # map: caller module -> set of anchors (module name, function name)
        self.dynamic_users = {}
        # map: file path to module path
        self.file_to_module = {}
        self.log_file = None
        self.prefixes = set()
        self.patches = None

    def start_tracking(self, prefixes: Set[str],
                       patches: Optional[Mapping[str, Any]] = None,
                       record_dynamic: bool = False,
                       dynamic_anchors: Optional[Mapping[str, Set[str]]] = None,
                       dynamic_ignores: Optional[Mapping[str, Set[str]]] = None,
                       log_file: Optional[str] = None,
                       ) -> None:
        # The usual "public" hook is builtins.__import__
        # Hooking in there is not great for our purpose as it only catches
        # explicit imports, and the internal logic which implicitly loads
        # parent __init__.py and submodules bypasses __import__ in favor
        # of internal helpers
        # We hook into _find_and_load, which is a private implementation
        # detail but appears to be stable from at least 3.7 all the way to
        # the most recent 3.13 release.
        # It is a great place for us because it is called before any check
        # for cached values in sys.modules, but after sanity checks and
        # resolution of relative imports, and crucially it is called even
        # for implicit loading
        # NB: we MUST use getattr/setattr to access those private members
        bs = getattr(importlib, '_bootstrap')
        self.old_find_and_load = getattr(bs, '_find_and_load')
        # we also need to hook into _handle_fromlist to catch the case where
        #   from foo import bar
        # with foo.bar being a module, as _find_and_load may not be called
        # on instances of this statement beyond the first one...
        self.old_handle_fromlist = getattr(bs, '_handle_fromlist')

        self.prefixes = prefixes
        self.patches = patches
        self.dynamic_anchors = dynamic_anchors or set()
        self.dynamic_ignores = dynamic_ignores or set()

        # resolve anchors to already-loaded modules
        # the rest will be resolved as needed when relevant modules are loaded
        for mod_name, m in sys.modules.items():
            if hasattr(m, '__file__'):
                self.file_to_module[m.__file__] = mod_name
            if dynamic_anchors and mod_name in dynamic_anchors:
                for fn in dynamic_anchors[mod_name]:
                    self.add_dynamic_usage_recorder(m, mod_name, fn)
        if log_file:
            self.log_file = log_file if isinstance(log_file, io.IOBase) else open(log_file, 'a')
            print("--- start tracking ---", file=self.log_file)

        def _new_find_and_load(name: str, import_: Any) -> Any:
            # only track relevant namespace
            base_ns = name.partition('.')[0]
            if base_ns not in self.prefixes:
                return self.old_find_and_load(name, import_)

            dynamic_idx, dynamic_anchor = self.record_dynamic_imports(
                traceback.extract_stack()
            ) if record_dynamic else (-1, None)

            if dynamic_idx == -1:
                return self._find_and_load_helper(name, import_)

            dynamic_base = None
            if dynamic_anchor:
                dynamic_base = self.cxt.copy()
                # NB: we have to mark ourselves here, as we haven't yet added
                # the modules in the stack to the file->module map so the
                # wrapped function cannot resolve those filenames yet...
                if self.log_file:
                    print(f"use from {self.stack[-1]}", file=self.log_file)
                self.dynamic_users.setdefault(self.stack[-1], set()).add(dynamic_anchor)

            try:
                return self._find_and_load_helper(name, import_)
            finally:
                if name in self.dynamic_users:
                    self.dynamic_users.setdefault(self.stack[-1], set()).update(self.dynamic_users[name])

                # record dynamic imports
                self.dynamic_stack = dynamic_idx
                if dynamic_anchor:
                    self.dynamic_imports.setdefault(
                        dynamic_anchor, set()
                    ).update(self.cxt - dynamic_base)

        def _new_handle_fromlist(module, fromlist, import_, **kwargs):
            if hasattr(module, '__path__'):
                base_ns = module.__name__.partition('.')[0]
                if base_ns in self.prefixes:
                    for x in fromlist:
                        if not (isinstance(x, str) and x != '*' and hasattr(module, x)):
                            continue
                        # this branch isn't going to reach _find_and_load
                        # so we must add tracking info manually if relevant
                        from_name = '{}.{}'.format(module.__name__, x)
                        from_val = getattr(module, x)
                        # is this actually a module?
                        if not isinstance(from_val, types.ModuleType):
                            continue
                        canonical = from_val.__name__
                        if canonical != from_name and canonical.partition('.')[0] not in self.prefixes:
                            continue
                        if self.log_file:
                            print(f"tracked:{' ' * len(self.stack)}{canonical} [fromlist: {from_name}]", file=self.log_file)
                        self.cxt.add(canonical)
                        if canonical in self.tracked:
                            self.cxt.update(self.tracked[canonical])

            return self.old_handle_fromlist(module, fromlist, import_, **kwargs)


        setattr(bs, '_find_and_load', _new_find_and_load)
        setattr(bs, '_handle_fromlist', _new_handle_fromlist)

        # we also override builtins __import__ to point to importlib's version
        # why? because the builtins hits the module cache too early, leading
        # to inconsistent results depending on the order in which modules are
        # loaded
        self.old_builtins_import = builtins.__import__
        builtins.__import__ = _builtins_import_no_cache


    def stop_tracking(self) -> None:
        if self.log_file:
            print("--- stop tracking ", file= self.log_file)
            print("tracked: ", self.tracked, file= self.log_file)
            print("dynamic imports:", self.dynamic_imports, file= self.log_file)
            print("dynamic users:", self.dynamic_users, file= self.log_file)
            if not isinstance(self.log_file, io.StringIO):
                self.log_file.close()

        bs = getattr(importlib, '_bootstrap')
        setattr(bs, '_handle_fromlist', self.old_handle_fromlist)
        setattr(bs, '_find_and_load', self.old_find_and_load)
        builtins.__import__ = self.old_builtins_import

    def enter_context(self, cxt):
        self.stack.append(cxt)

    def exit_context(self, expected):
        actual = self.stack.pop()
        if actual != expected:
            raise ValueError(f"mismatching context entry/exit: {actual} != {expected}")

    def with_dynamic(self, m) -> Set[str]:
        dyn = {
            i
            for u in self.dynamic_users.get(m, ())
            for i in self.dynamic_imports.get(u, ())
        }
        return self.tracked[m] | dyn


    def _find_and_load_helper(self, name: str, import_: Any) -> Any:
        new_context = False
        self.cxt.add(name)
        if self.log_file:
            flag = '*' if name in self.tracked else ('+' if name in sys.modules else ' ')
            print(f"tracked:{' ' * len(self.stack)}{name} {flag}", file=self.log_file)
        if name in self.tracked:
            # we're already tracking this one
            #  - fully resolved: tracked[] has the full transitive deps
            #  - import cycle: tracked[] deps might not be complete

            start_idx = next((i for i, v in enumerate(self.stack) if v == name), -1)
            if start_idx == -1:
                self.cxt.update(self.tracked[name])
            else:
                # every entry of an import cycle ends up with an identical
                # set of transitive deps. let's go ahead and consolidate them
                # so that they all point to the same underlying set() instance
                cycle = self.stack[start_idx:]

                if self.log_file:
                    print("warn: cycle {} -> {}".format(cycle, name),
                          file=self.log_file)

                # there might be multiple import cycles overlapping in the stack,
                # fortunately, we're guaranteed that every module within a cycle
                # will be part of the current stack.
                # When consolidating, it is important to preserve the set()
                # instance used by the first entry in the current cycle, as that
                # might be part of a previous cycle extending earlier in the
                # stack. Modifying that set in place means that if the module at
                # the start of the current cycle is already part of the cycle,
                # we're transparently extending the previous cycle without having
                # to even detect its presence!
                consolidated = self.tracked[name]
                for mod in cycle[1:]:
                    deps = self.tracked[mod]
                    if deps is not consolidated:
                        consolidated.update(deps)
                        self.tracked[mod] = consolidated

                self.cxt = consolidated
        else:
            # not tracked yet: push a new context into the stack
            # NB: the set is a reference, not a value, so changes to cxt
            # are reflected in tracked[name], saving some indirections
            tdeps = set()
            self.tracked[name] = tdeps
            self.stack.append(name)
            self.cxt = tdeps
            # mark that we need to pop down after forwarding
            new_context = True

        has_err = False
        try:
            # forward to real implementation
            m = self.old_find_and_load(name, import_)

            # maintain a mapping of file path to module name
            # this is later used to map filepath from stack frame to module
            if hasattr(m, '__file__'):
                self.file_to_module[m.__file__] = name

            # apply any necessary patches immediately after loading module
            if self.patches is not None and name in self.patches:
                apply_patches(name, self.patches)

            # parent __init__ are implicitly resolved, but sys.modules is
            # checked *before* calling _gcd_import so our _find_and_load
            # monkey-patch only catches the first occurrence of implicit
            # parent resolution. We need to manually reify this dep.
            # We only need to do that for the immediate parent as its
            # set of deps is either already fully resolved, including its
            # own parent, or partially resolved in a cycle that is being
            # consolidated...
            parent = name.rpartition('.')[0]
            if parent and parent not in self.cxt and parent in self.tracked:
                self.cxt.add(parent)
                self.cxt.update(self.tracked[parent])
                if parent in self.dynamic_users:
                    self.dynamic_users.setdefault(name, set()).update(self.dynamic_users[parent])

            if name in self.dynamic_anchors:
                # wrap the methods to record dynamic usage
                for fn_name in self.dynamic_anchors[name]:
                    self.add_dynamic_usage_recorder(m, name, fn_name)

            return m
        except BaseException as e:
            has_err = True
            if self.log_file:
                print(f"warn: {e}", file=self.log_file)
            if new_context:
                # defer removal from self.tracked[] if we're within an import cycle
                # NB: this should happen if there's an uncaught import error, in
                # affirm code, which is not expected in practice, unless something
                # is wrong with the codebase, but better safe than sorry...
                if name not in self.stack[:-1]:
                    del self.tracked[name]
            raise
        finally:
            # pop down context if we pushed one earlier, and propagate deps down the stack
            if new_context:
                self.stack.pop()
                n = self.stack[-1]
                down = self.tracked[n]
                # avoid potentially expensive no-op for cycles
                if down is not self.cxt:
                    down.update(self.cxt)
                self.cxt = down

                if has_err:
                    # we optimistically added a dependency before resolving the module
                    # remove it to avoid reporting spurious dependencies
                    # TODO: track "optional" deps separately?
                    self.cxt.discard(name)


    def add_dynamic_usage_recorder(self, module: str, module_name: str, fn_name: str) -> None:
        """
        Wraps a given function from a given module to record subsequent usages from
        other modules.

        The wrapper function walks the stack, mapping filenames to module names, and
        adds all successfully resolved modules to the set of users of the wrapped
        function.

        At a later point the combined imports from this function can be integrated
        into the dependencies for all caller modules
        """
        def wrapped_fn(*args, **kwargs):
            tb = traceback.extract_stack()
            if self.log_file:
                print(f"use: ({module_name}, {fn_name})", file=self.log_file)
            for frame in tb:
                caller_mod = self.file_to_module.get(frame.filename)
                # NB: only record dynamic use within tracked namespaces
                if caller_mod and caller_mod.partition('.')[0] in self.prefixes:
                    if self.log_file:
                        print(f"> use from {caller_mod}", file=self.log_file)
                    self.dynamic_users.setdefault(caller_mod, set()).add((module_name, fn_name))
            return fn(*args, **kwargs)

        if '.' in fn_name:
            obj, method = fn_name.split('.', maxsplit=1)
            if hasattr(module, obj):
                o = getattr(module, obj)
                if hasattr(o, method):
                    fn = getattr(o, method)
                    # TODO: patch the underlying class instead?
                    setattr(o, method, wraps(fn)(wrapped_fn))
        elif hasattr(module, fn_name):
            fn = getattr(module, fn_name)
            setattr(module, fn_name, wraps(fn)(wrapped_fn))


    def record_dynamic_imports(self, tb: traceback.StackSummary) -> Tuple[int, Optional[str]]:
        # walk down the stack until we either find a recognizable dynamic import,
        # our import hook, or an import from the validator
        n = len(tb)
        found = -1

        # record stack height of previous dynamic import to restore
        prev_stack = self.dynamic_stack
        assert prev_stack < n, f"{prev_stack} {n}"

        i = 2
        while i < n:
            # we've reached the previous dynamic import without finding a new one
            if prev_stack == n-i:
                break
            frame = tb[n-i]
            # TODO: check filename as well
            if frame.name in {"import_module", "load_module"}:
                found = n-i
                break
            if frame.name == "__import__":
                # NB: because we override builtins.import to avoid early cache hits,
                # we have to filter out our override to avoid incorrectly treating
                # normal imports as dynamic imports...
                if n-i-1 > 0 and tb[n-i-1].filename == __file__:
                    i += 2
                    continue
                found = n-i
                break

            # NB: builtins.__import__ and importlib.__import__ lead to different stacks
            # for some reason the builtin is elided from the stack so catching a dynamic
            # import that uses the builtin requires looking at the actual code, which is
            # less reliable since the code is not always available...
            if "__import__(" in frame.line:
                found = n-i+1
                break

            i += 1

        # ignore if it's coming from the validator
        if found == -1 or is_validator_frame(tb[found-1]):
            return -1, None

        # record relevant slice of backtrace, stripping out anything pre-validator
        start = prev_stack + 1 + max(
            (i if is_validator_frame(frame) else -1
             for i, frame in enumerate(tb[prev_stack:found])),
            default=-1
        )
        dyn_stack = list(omit_tracker_frames(tb[start:found]))

        if self.log_file:
            print(f"dynamic:{' ' * len(self.stack)}: {dyn_stack}", file=self.log_file)

        # look for the first occurrence of a known aggregation point in the relevant
        # portion of the stack trace, or for an ignore point
        anchor = None
        last_candidate = None

        # keep track of where in the stack of tracked imports we are
        # So we can resolve filenames for modules currently being imported
        stack_off = 0
        fresh_import = False

        for i, frame in enumerate(tb[:found]):
            if frame.filename == __file__ and frame.name == '_find_and_load_helper':
                stack_off += 1
                fresh_import = True
            if frame.filename in IGNORED_FRAMES:
                continue

            mod = self.file_to_module.get(frame.filename)
            # if the file is not in our map, and we just came out of the import machinery
            # we've found our mapping!
            if not mod and fresh_import:
                mod = self.stack[stack_off]
                if self.log_file:
                    print(f'resolving: {frame.filename} {mod}', file=self.log_file)
                self.file_to_module[frame.filename] = mod

            fresh_import = False

            # early stack walk is only for the purpose of name resolution...
            if i < start or not mod:
                continue

            if mod in self.dynamic_ignores and frame.name in self.dynamic_ignores[mod]:
                return -1, None
            if mod in self.dynamic_anchors and (
                    frame.name in self.dynamic_anchors[mod]
                    or any(a.rpartition('.')[2] == frame.name for a in self.dynamic_anchors[mod])
            ):
                anchor = (mod, frame.name)
                break
            if mod.partition('.')[0] in self.prefixes:
                last_candidate = (mod, frame.name)

        # if no explicit aggregation point is found, pick the topmost stack entry that
        # corresponds to a module being tracked
        if not anchor:
            anchor = last_candidate

        if self.log_file:
            print(f"dynamic:{' ' * len(self.stack)}: {anchor}", file=self.log_file)

        # mark stack height of dynamic import
        self.dynamic_stack = len(tb)

        # only record stack for unexpected dynamic imports
        if anchor is None:
            self.dynamic.append(dyn_stack)
        return prev_stack, anchor