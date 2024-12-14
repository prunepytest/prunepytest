#! /bin/bash
set -eu -o pipefail

readonly abs_dir=$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)

cd "${abs_dir}/pyext"

if command -v uv ; then
  mk_venv=(uv venv)
  install_deps=(uv pip sync)
  maturin=(uvx maturin)
  pip=(uv pip)
else
  mk_venv=(python3 -m venv)
  install_deps=(python -m pip install -r)
  maturin=(maturin)
  pip=(python3 -m pip)
fi

if [[ ! -d .venv ]] ; then
  "${mk_venv[@]}" .venv
fi
source .venv/bin/activate

pyver=$(python -c 'import sys ; print(".".join(str(v) for v in sys.version_info[0:2]))')
pyminor=$(echo "$pyver" | cut -d. -f 2)
if (( "$pyminor" > 7 )); then
  if [[ "${PY_COVERAGE:-1}" == "1" ]] ; then
    "${install_deps[@]}" requirements-dev.txt
  else
    "${install_deps[@]}" <(grep -Fv slipcover requirements-dev.txt)
  fi
else
  "${install_deps[@]}" requirements-3.7.txt
fi

maturin_mode=()
if [[ -z "${INSTALL_ARGS:-}" ]] ; then
  if [[ "${RUST_COVERAGE:-}" == "1" ]] ; then
    cargo llvm-cov show-env --export-prefix > .cov.env
    source .cov.env
    cargo llvm-cov clean --workspace
    # manylinux compat without going into  container
    # TODO: restrict to linux
    pip install maturin[zig]
    maturin_mode=(--zig)
  else
    maturin_mode=(--release)
  fi

  # auto-build and install wheel
  "${pip[@]}" install \
    "$("${maturin[@]}" build ${maturin_mode+"${maturin_mode[@]}"} 2>&1 \
    | tee /dev/stderr \
    | grep -F 'Built wheel' \
    |  grep -Eo '[^ ]+.whl$' \
    )" --force-reinstall
else
  # NB: lack of quotes around ${INSTALL_ARGS} is intentional
  "${pip[@]}" install ${INSTALL_ARGS}
fi

echo
# slipcover does not support 3.7, but we still do
if (( "$pyminor" > 7 )) && [[ "${PY_COVERAGE:-1}" == "1" ]]; then
  echo "--- pytest, with coverage"
  # TODO: enforce coverage thresholds
  libpath=".venv/lib/python$pyver"
  python -m slipcover --source $libpath/site-packages/prunepytest -m pytest --rootdir python
else
  echo "--- pytest, without coverage (${pyver} not supported by slipcover)"
  python -m pytest --rootdir python
fi

# mypy has dropped support for 3.7 but we still support it...
if (( "$pyminor" > 7 )) ; then
  echo
  echo "--- mypy"
  python -m mypy --strict --check-untyped-defs -p prunepytest
fi

cd "${abs_dir}"

if [[ "${RUST_COVERAGE:-}" == "1" ]] ; then
  echo
  echo "--- rust tests"
  cargo nextest run

  echo
  echo "--- rust coverage"
  cargo llvm-cov report --html
fi
