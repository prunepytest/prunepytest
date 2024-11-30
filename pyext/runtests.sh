#! /bin/bash
set -e -o pipefail

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

pyver=$(python --version | cut -w -f 2)
if (( "$(echo "$pyver" | cut -d. -f 2)" > 7 )) ; then
  "${install_deps[@]}" requirements-dev.txt
else
  "${install_deps[@]}" requirements-3.7.txt
fi

if [[ -z "${INSTALL_ARGS}" ]] ; then
  # auto-build and install wheel
  "${pip[@]}" install \
    "$("${maturin[@]}" build --release 2>&1 \
    | tee /dev/stderr \
    | grep -F 'Built wheel' \
    |  grep -Eo '[^ ]+.whl$' \
    )" --force-reinstall
else
  "${pip[@]}" install ${INSTALL_ARGS}
fi

if (( "$(echo "$pyver" | cut -d. -f 2)" > 7 )) ; then
  echo "With coverage"
  # TODO: enforce coverage thresholds
  libpath=.venv/lib/python$(echo $pyver | cut -d. -f1,2)
  python -m slipcover --source $libpath/site-packages/testfully -m pytest --rootdir python
else
  echo "Without coverage (${pyver} not supported by slipcover)"
  python -m pytest --rootdir python
fi
