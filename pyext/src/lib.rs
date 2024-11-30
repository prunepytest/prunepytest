use log::ParseLevelError;
use pyo3::exceptions::{PyException, PyTypeError};
use pyo3::marker::Ungil;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyNone, PySequence, PySet, PyString};
use pyo3::IntoPyObjectExt;
use std::collections::{HashMap, HashSet};
use ustr::{Ustr, UstrSet};

use common::graph;
use common::parser;
use common::transitive_closure::TransitiveClosure;

fn to_vec<'py, T>(v: Bound<'py, PyAny>) -> PyResult<Vec<T>>
where
    T: FromPyObject<'py>,
{
    if let Ok(_) = v.downcast::<PyNone>() {
        Ok(vec![])
    } else if let Ok(seq) = v.downcast::<PySequence>() {
        Ok(seq.extract::<Vec<T>>()?)
    } else if let Ok(set) = v.downcast::<PySet>() {
        let mut r = Vec::with_capacity(set.len());
        for v in set {
            r.push(v.extract::<T>()?);
        }
        Ok(r)
    } else {
        Err(PyErr::new::<PyTypeError, _>("Expected a sequence or a set"))
    }
}

#[pyclass(subclass, module = "testfully")]
pub struct ModuleGraph {
    tc: TransitiveClosure,
}

#[pymethods]
impl ModuleGraph {
    #[new]
    #[pyo3(signature = (packages, global_prefixes, local_prefixes,
                        external_prefixes=HashSet::default(),
                        dynamic_deps=HashMap::default(),
    ))]
    fn new<'py>(
        py: Python<'py>,
        packages: HashMap<String, String>,
        global_prefixes: HashSet<String>,
        local_prefixes: HashSet<String>,
        external_prefixes: HashSet<String>,
        dynamic_deps: HashMap<String, HashSet<String>>,
    ) -> PyResult<ModuleGraph> {
        let tc = py
            .allow_threads(|| {
                let g = graph::ModuleGraph::new(
                    packages,
                    global_prefixes,
                    local_prefixes,
                    external_prefixes,
                );
                g.parse_parallel()?;
                if !dynamic_deps.is_empty() {
                    g.add_dynamic_dependencies(dynamic_deps);
                }
                Ok(g.finalize())
            })
            .or_else(|e: parser::Error| return Err(PyErr::new::<PyException, _>(e.to_string())))?;
        Ok(ModuleGraph { tc })
    }

    #[staticmethod]
    #[pyo3(signature = (filepath))]
    fn from_file<'py>(py: Python<'py>, filepath: &str) -> PyResult<ModuleGraph> {
        Ok(ModuleGraph {
            tc: py
                .allow_threads(|| TransitiveClosure::from_file(filepath))
                .or_else(|e| Err(PyErr::new::<PyException, _>(e.to_string())))?,
        })
    }

    #[pyo3(signature = ())]
    fn unresolved<'py>(&self) -> PyResult<HashMap<String, HashSet<String>>> {
        Ok(self.tc.unresolved())
    }

    #[pyo3(signature = (filepath))]
    fn to_file<'py>(&self, py: Python<'py>, filepath: &str) -> PyResult<()> {
        py.allow_threads(|| self.tc.to_file(filepath))
            .or_else(|e| Err(PyErr::new::<PyException, _>(e.to_string())))
    }

    #[pyo3(signature = (simple_unified, simple_per_package))]
    fn add_dynamic_dependencies_at_edges<'py>(
        &mut self,
        py: Python<'py>,
        simple_unified: Vec<(String, HashSet<String>)>,
        simple_per_package: Vec<(String, HashMap<String, HashSet<String>>)>,
    ) -> PyResult<()> {
        py.allow_threads(|| {
            self.tc
                .apply_dynamic_edges_at_leaves(&simple_unified, &simple_per_package)
        });
        Ok(())
    }

    #[pyo3(signature = (filepath))]
    fn file_depends_on<'py>(&self, py: Python<'py>, filepath: &str) -> PyResult<Bound<'py, PyAny>> {
        match self.tc.file_depends_on(filepath) {
            None => PyNone::get(py).into_bound_py_any(py),
            Some(deps) => {
                let r = PySet::empty(py).or_else(|e| return Err(e))?;
                for dep in &deps {
                    r.add(PyString::new(py, dep))?;
                }
                r.into_bound_py_any(py)
            }
        }
    }

    #[pyo3(signature = (module_import_path, package_root = None))]
    fn module_depends_on<'py>(
        &self,
        py: Python<'py>,
        module_import_path: &str,
        package_root: Option<&str>,
    ) -> PyResult<Bound<'py, PyAny>> {
        match self.tc.module_depends_on(module_import_path, package_root) {
            None => PyNone::get(py).into_bound_py_any(py),
            Some(deps) => {
                let r = PySet::empty(py).or_else(|e| return Err(e))?;
                for dep in &deps {
                    r.add(PyString::new(py, dep))?;
                }
                r.into_bound_py_any(py)
            }
        }
    }

    #[pyo3(signature = (files))]
    fn affected_by_files<'py>(
        &self,
        py: Python<'py>,
        files: Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyDict>> {
        affected_by(py, files, |l| self.tc.affected_by_files(l))
    }

    #[pyo3(signature = (modules))]
    fn affected_by_modules<'py>(
        &self,
        py: Python<'py>,
        modules: Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyDict>> {
        affected_by(py, modules, |l| self.tc.affected_by_modules(l))
    }
}

fn affected_by<'py, F>(py: Python<'py>, l: Bound<'py, PyAny>, f: F) -> PyResult<Bound<'py, PyDict>>
where
    F: Ungil + Send + FnOnce(Vec<String>) -> HashMap<Ustr, UstrSet>,
{
    let modules: Vec<String> = to_vec(l).or_else(|e| return Err(e))?;
    let affected = py.allow_threads(|| f(modules));

    let r = PyDict::new(py);
    for (pkg, test_files) in &affected {
        let files = PySet::empty(py)?;
        for file in test_files {
            files.add(PyString::new(py, &file))?
        }
        r.set_item(PyString::new(py, &pkg), files)?
    }

    Ok(r)
}

#[pyfunction]
fn configure_logger<'py>(file: String, level: String) -> PyResult<()> {
    fern::Dispatch::new()
        .format(|out, message, record| out.finish(format_args!("{}: {}", record.level(), message)))
        .level(
            level
                .parse()
                .or_else(|e: ParseLevelError| Err(PyErr::new::<PyException, _>(e.to_string())))?,
        )
        .chain(fern::log_file(file)?)
        .apply()
        .or_else(|e| Err(PyErr::new::<PyException, _>(e.to_string())))?;
    Ok(())
}

#[pymodule]
fn _testfully(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ModuleGraph>()?;
    m.add_function(wrap_pyfunction!(configure_logger, m)?)?;
    Ok(())
}
