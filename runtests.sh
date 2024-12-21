#! /bin/bash
set -eu -x -o pipefail

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
    # filter out slipcover when python coverage is disabled
    # NB: part of the reason we allow disabling coverage on platforms that slipcover
    # does support is because binary wheels are not provided for all of those, and
    # building those wheels requires a full C/C++ toolchain, which is particularly
    # expensive to install in the virtualized arm64 tests on github actions
    "${install_deps[@]}" <(grep -Fv slipcover requirements-dev.txt)
  fi
else
  "${install_deps[@]}" requirements-3.7.txt
fi

maturin_mode=()
if [[ "${RUST_COVERAGE:-}" == "1" ]] ; then
  cargo llvm-cov show-env --export-prefix > .cov.env
  source .cov.env
  cargo llvm-cov clean --workspace
  if [[ -n "${MATURIN_FLAGS:-}" ]] ; then
    maturin_mode=(${MATURIN_FLAGS})
  fi
else
  maturin_mode=(--release)
fi
if [[ -z "${INSTALL_ARGS:-}" ]] ; then
  new_wheel="$("${maturin[@]}" build ${maturin_mode+"${maturin_mode[@]}"} 2>&1 \
      | tee /dev/stderr \
      | grep -F 'Built wheel' \
      |  grep -Eo '[^ ]+.whl$' \
      )"

  INSTALL_ARGS="${new_wheel}"
fi

# NB: lack of quotes around ${INSTALL_ARGS} is intentional
"${pip[@]}" install ${INSTALL_ARGS} --force-reinstall

echo
# slipcover does not support 3.7, but we still do
if (( "$pyminor" > 7 )) && [[ "${PY_COVERAGE:-1}" == "1" ]]; then
  echo "--- pytest, with coverage"
  # for extra tests below...
  export PY_COVERAGE=1
  libpath=".venv/lib/python$pyver"
  cover_args=(-m slipcover --source $libpath/site-packages/prunepytest)
  if [[ -n "${EXTRA_TESTS:-}" ]] ; then
    cover_args+=(--json --out cov.main.json)
  fi
  python "${cover_args[@]}" -m pytest --rootdir python
else
  # for extra tests below...
  export PY_COVERAGE=0
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

# TODO: support running rust tests without coverage?
if [[ "${RUST_COVERAGE:-}" == "1" ]] ; then
  echo
  echo "--- rust tests"
  cargo nextest run
fi

if [[ -n "${EXTRA_TESTS:-}" ]] ; then
  echo
  echo "--- extra tests: ${EXTRA_TESTS}"
  export PRUNEPYTEST_INSTALL="${INSTALL_ARGS}"
  export PY_COVERAGE_OUT="$(pwd)/cov.extra.json"
  ${EXTRA_TESTS}

  python -m slipcover --out cov.merged.json --merge pyext/cov.main.json cov.extra.json
  # TODO: show report for merged coverage file
fi

if [[ "${RUST_COVERAGE:-}" == "1" ]] ; then
  echo
  echo "--- rust coverage"
  covargs=(--ignore-filename-regex cmd/)
  cargo llvm-cov report "${covargs[@]}" --lcov --output-path lcov.info
  cargo llvm-cov report "${covargs[@]}" --html
fi
