prunepytest
===========

[![CI](https://github.com/prunepytest/prunepytest/actions/workflows/CI.yml/badge.svg)](https://github.com/prunepytest/prunepytest/actions/workflows/CI.yml)
[![codecov](https://codecov.io/gh/prunepytest/prunepytest/graph/badge.svg?token=2I5G1BGT7R)](https://codecov.io/gh/prunepytest/prunepytest)
[![pypi](https://img.shields.io/pypi/v/prunepytest?color=blue)](https://pypi.org/project/prunepytest/)

Do you have lots of Python tests?

Do you find yourself wondering whether you really need to run the full test suite
for every tiny change?

Do you wish to know exactly which tests to run to assess the soundness of any
given change?

Would you plausibly save a significant amount of time (and possibly money if your
CI budget is significant) by skipping irrelevant tests?

Then prunepytest might be for you! Make sure you read the [LICENSE](LICENSE) first though.

## Who can use this ?

As per the terms of the [LICENSE](LICENSE), this software can be freely used as long
as the code under test is either publicly available under an open source license, or
private and never shared with anyone.

If you wish to use this on code that more than one individual can access, but that is
not publicly available under an OSI or FSF approved license, you may take advantage of
the trial period for up to 15 days per calendar year. After that, you MUST either obtain
my written permission to continue using the software, or wait for usage restrictions to
be lifted, 4 years after the initial public release, just in time for Christmas 2028.

[Contact me](mailto:hugues@betakappaphi.com)

## Installation

```bash
pip install prunepytest
```

## How does it work?

prunepytest operates by first building an accurate module-level import graph for
your Python code.

Then, based on that import graph, and a set of modified files (either provided
explicitly, or inferred from a version control system), it is able to determine
a *safe* set of test files that should be run.

The main interface is a [pytest](https://pytest.org) plugin that is intended to
work out-of-the-box for most simple Python projects.

```bash
pytest --prune
```

The import graph can be computed very quickly by using a native extension, written
in Rust with [PyO3](https://pyo3.rs), which leverages the fast Python parser from
[ruff](https://astral.sh/ruff), and the parallel directory walker from
[ripgrep](https://github.com/BurntSushi/ripgrep).

The combination of efficient native code with built-in support for parallelism means
that a large codebase that would take over a minute to parse with Python's own `ast`
module can be fully parsed, and have its transitive import closure computed in a matter
of seconds!


## Validating the import graph

Unfortunately, the Python import machinery is notoriously complex, due to the
possibility arbitrary code execution at import time, and the ability to perform
dynamic imports at  run-time. For projects that depend on those features, it is
important to first validate  the accuracy of the import graph before relying on
prunepytest for test selection.

### import-time validation

As a first step, it is often useful to do a quick import-time validation, which
works by:
 - computing a static import graph by parsing the Python code
 - hooking into the import machinery, then importing all test code, to obtain an
   accurate picture of the *actual* import graph.
 - validating that the set of static imports obtained from parsing is a *superset*
   of the set obtained by importing the code

```bash
python -m prunepytest validate
```

### test-time validation

By default, prunepytest does the safe thing, and reports all unexpected dynamic
imports within a test context as failures. However, this will only validate tests
that are being run. Before rolling out prunepytest in a CI system, it is highly
advisable to do a first full-scale test-time validation, by disabling test pruning,
via the `--prune-no-select` flag:

```bash
pytest --prune --prune-no-select
```

Test-time validation can be explicitly disabled via the `--prune-no-validate` flag
```bash
pytest --prune --prune-no-validate
```

Alternatively, the errors can be downgraded to warnings, via the `--prune-no-fail` flag.
```bash
pytest --prune --prune-no-fail
```

## Sensible defaults, and overriding them

Both the import-time validator and the pytest plugin have sensible defaults: they
scan the repository under test to automatically detect relevant Python packages,
and attempt to detect common configuration files (such as `pyproject.toml`) to
automatically adjust to slight deviations from conventions.

For more complicated repository layouts, the default behavior might not quite work.
This can be addressed by creating a Python file that contains an implementation of
`prunepytest.api.PluginHook` or `prunepytest.api.ValidatorHook` and point prunepytest
to this file:

```bash
pytest --prune --prune-hook hook.py
```

For slight deviations, it is possible to subclass `prunepytest.DefaultHook` instead
of starting from scratch, to leverage sensible defaults as a starting point.

For more details, refer to docstrings in [`api.py`](pyext/python/src/prunepytest/api.py)

## Dealing with dynamic imports

If validation points to inaccuracies in the static import graphs, there are a few ways
to deal with that.

### Providing hints to the import parser

To ensure maximum accuracy, the import parser goes *deep*, and considers all import
statements, not just at-module level, but arbitrarily nested, whether inside functions
or conditional blocks.

This makes it extremely easy to provide hints about dynamic imports to the parser,
by gating import statements behind an always-False conditional:

```python
if False:  # for the import parser
  import foo.bar  # noqa: F401
```

For improved usability, the import parser also departs from the specification of the
import machinery when it comes to wildcard imports. Specifically, while the Python
interpreter depends on an explicit listing of submodules in the `__all__` variable of
a package's `__init__.py`, prunepytest will instead scan the filesystem, and resolve
a wildcard to all existing modules next to the `__init__.py`. This makes it more
practical to provide hints that encompass a large number of submodules, without having
to update the hints every time modules are added or removed.

### Considering typechecking-only imports

One notable exception to the "parser goes deep" outlined above is that, by default,
typechecking-only imports are excluded from  the import graph. If that exclusion is
undesirable, it can be changed through a hook:

```python
from prunepytest.api import DefaultHook

class Hook(DefaultHook):
   def include_typechecking(self) -> bool:
      return True
```

### Specifying extra dependencies via a custom Hook

There are two main hooks to specify extra dependencies:

 - `dynamic_dependencies()`, returns a mapping from module (specified as Python import
 path or filepath) to set of extra imports (specified as Python import paths, possibly
 including wildcards).  
 Those extra dependencies are incorporated into the graph before computing the transitive
 closure.

 - `dynamic_dependencies_at_leaves()`, returns a sequence of entries to be incorporated
 *after* computing of the transitive closure of the import graph.  
 This can be useful when, for instance, a common method triggers dynamic import based
 on a configuration file, and that file differs across source roots.  
 In such a case, it would be possible to explicitly specifying extra dependencies for
 each test file relying on that method but that might be tedious and brittle. Assigning
 *varying* dependencies to the common module offers a more succinct and robust way to
 specify the same dynamic dependency information.

### Sample hooks

Sample implementations for some real-world open source projects are available in
[prunepytest-validation](https://github.com/taste-prune-pie/prunepytest-validation):

 - [pydantic v1](https://github.com/taste-prune-pie/prunepytest-validation/tree/main/repos/pydantic.v1/hook.py)
 - [pydantic v2](https://github.com/taste-prune-pie/prunepytest-validation/tree/main/repos/pydantic/hook.py)


## Reusing the import graph

In cases where the import graph is large and slow to build, it can be worth saving it
in a serialized form to reuse across multiple commands.

```bash
# collect and save import graph
# NB: this is a no-op if a valid graph exists
python -m prunepytest graph --prune-graph graph.bin

# use the existing graph instead of parsing source code again
pytest --prune --prune-graph graph.bin
```

## Limitations

Because it only relies on a statically derived import graph, prunepytest can be used
immediately, without needing a first full run of the test suite to collect dependency
information (although it might be worth doing a validation run, as explained earlier),
and saving/transferring that information across builds.

However, that also means that it will not catch more complicated test dependencies,
such as dependencies on config files, or data-driven test cases.

Handling such dependencies in the general case is possible, for instance through
syscall-tracing, but intentionally out-of-scope of this project. A future release
might add some facility to explicitly annotate non-Python dependencies, until then,
the handling of non-Python dependencies in the context of test selection is left as
an exercise for the user.

The pytest plugin does a limited best-effort handling of data-driven test cases,
inspired by the desire to support [mypy](https://github.com/python/mypy)'s test
suite. Contributions intended to expand this to a broader set of data-driven test
cases would be welcome.


## FAQ

  - **What environments are supported?**  
  The minimum required Python version is 3.7  
  The minimum required pytest version is 7.2  
  Linux (x86_64, arm64), macOS (x86_64, arm64), and Windows (x86, x86_64) are supported,
  covered in CI, and available as pre-built binary wheels on PyPI. More environments may
  be added in the future based on demand.  


  - **Is this compatible with [xdist](https://pytest-xdist.readthedocs.io/)?**  
  Yes!  
  The pytest plugin will automatically detect whether xdist is being used, and make
  necessary adjustments to avoid redundant import graph computation, and ensure
  continued correctness of test-time validation.  
  NB: this has only been tested with `pytest-xdist==3.6.1`


  - **What about `<other pytest plugin>`?**  
  While there is no a-priori expectation of incompatibility, it is not practical to
  test interactions with all popular pytest plugins. Feel free to report any issue.


  - **How does this compare to [`pytest-testmon`](https://testmon.org/)?**  
  testmon is the only other attempt I am aware of to solve the problem of selecting
  a minimal safe set of tests to run based on modified files. Its design is based on
  detailed code coverage data, which has the potential to more aggressively prune the
  test set. However, it has a number of significant drawbacks:
    * testmon requires enabling code coverage with [`coverage.py`](https://coverage.readthedocs.io/),
      which typically incurs 2-4x slowdown. With prunepytest, you are free to leverage
      the amazing [slipcover](https://github.com/plasma-umass/slipcover) instead.
    * testmon requires a full initial test run to build the dependency database. For
      prunepytest, this is only relevant as a validation step for codebases that rely
      on dynamic imports.  
    * testmon still needs to parse the Python source code, which can add considerable
      overhead at test-selection time for large codebases.
    * In most cases, testmon's database is considerably larger than prunepytest's
      serialized import graph, which makes a big difference for distributed test runs.
    * testmon does not offer meaningful validation of its test selection logic, whereas
      prunepytest takes validation seriously, and has a comprehensive test suite that
      achieves a high level of code coverage.


  - **What's this weird [license](LICENSE) about?**  
  I started prototyping this code to support a contracting pitch to a software company in
  the financial sector. They would have probably saved upwards of $100k/month on EC2 costs
  alone!  
  They declined my proposal, and out of respect for their wishes to keep wasting money, I
  want to make sure the solution is *not* available to them for free ;)  
  At the same time, I believe this tool could be tremendously useful for many open source
  projects. This weird license is my attempt to strike a balance between serving the needs
  of the open source ecosystem while incentivizing large companies to pay for software that
  they derive significant value from.  


  - **So it's not actually Open Source?**  
  No.  
  This [license](LICENSE) is not OSI-approved, and the presence of usage restrictions go against
  the fundamental "freedom 0", so it is unlikely to ever get the stamp of approval from OSI
  or FSF.  
  

  - **But it will eventually be Open Source?**  
  Yes.  
  Four years after the initial public release.


  - **Can I use it in the CI system of some Open Source project?**  
  Yes.


  - **Can I use it in the CI system of some closed source project?**  
  You need to [contact me](mailto:hugues@betakappaphi.com) to get written permission.


  - **What if I make changes?**  
  The [license](LICENSE) still applies to any modified version. So using a modified version
  on open source code is fine, but using the modified version on code that is not open source
  would still require written permission from the [copyright owner](mailto:hugues@betakkaphi.com).


  - **Is anyone actually going to pay for this?**  
  Some people think that capitalism implies that corporations are rational actors, or at
  least tend to act more rationally that many individuals. If that were so, I would expect
  that any company with a significant Python codebase that incurs a large CI expenditure,
  and lacking the time or expertise to build equivalent software in-house, would be excited
  to pay for prunepytest.  
  Pay how much? At least as much as they would expect to save in the amount of time it
  would take them to build an equivalent in-house solution. And that would be arguably be a
  screaming deal, because they would be saving on the payroll required to fund an in-house
  alternative, avert the risk of the in-house project failing, and derive usability benefits
  beyond the CI cost savings.  
  Whether there are any companies that would both benefit from this software, and can
  rationally assess its value to them, is an open question.


  - **Can I contribute?**  
  Maybe.  
  You have to be willing to make your contribution under a sufficiently permissive license
  for me to integrate it, and ensure that any prospective private user only have to get
  written permission from a single entity.
  Basically that means BSD, MIT, Apache, or Unlicense/Public Domain.


  - **My codebase is too gnarly, help?!?**  
  If your codebase is open source, submit an issue in the tracker.  
  If your codebase is *not* open source, I am open to negotiating a contract to help integrate
  this software in your CI system. [Contact me](mailto:hugues@betakappaphi.com)
