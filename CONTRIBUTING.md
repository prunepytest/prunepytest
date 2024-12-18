## Minimum requirements for building from source

 - git
 - bash
 - Rust >=1.83
 - Python >= 3.7
 - [maturin](https://maturin.rs/) (automatically installed by [`runtests.sh`](runtests.sh))

We recommend using [uv](https://astral.sh/uv) to manage Python versions and venvs.

We recommend using [rustup](https://rustup.rs/) to manage Rust toolchains.

## Extra tools for testing

Requiring manual installation:
 - [cargo-nextest](https://nexte.st/)
 - [cargo-llvm-cov](https://github.com/taiki-e/cargo-llvm-cov)

Automatically installed by [`runtests.sh`](runtests.sh)
 - [pytest](https://pytest.org)
 - [mypy](https://github.com/python/mypy)
 - [slipcover](https://github.com/plasma-umass/slipcover)

## High-level test runner

From the root directory:
```bash
./runtests.sh
```

This will automatically compile the Rust code, build a Python wheel, install it
in a venv, run all Python tests with pytest, perform typechecking with
[mypy](https://github.com/python/mypy), and collect coverage information with
[slipcover](https://github.com/plasma-umass/slipcover) if possible.

To additionally run Rust tests and collect Rust coverage information:

```bash
RUST_COVERAGE=1 ./runtests.sh
```

## Running Rust tests

From the root directory:
```bash
cargo nextest run
```

## Running Rust benchmarks

From the root directory:
```bash
cargo bench -p common
```

We use [divan](https://github.com/nvzqz/divan)

## Building a Python wheel

From the `pyext` directory
```bash
uvx maturin build
```
