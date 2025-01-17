// SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

use crate::matcher::MatcherNode;
use crate::moduleref::{LockedModuleRefCache, ModuleRef, ModuleRefCache};
use crate::parser::raw_get_all_imports;
use crate::transitive_closure::TransitiveClosure;
use anyhow::Context;
use dashmap::{DashMap, Entry};
use ignore::{DirEntry, Error, WalkBuilder, WalkState};
use log::{debug, error, info, warn};
use std::collections::{HashMap, HashSet};
use std::path::{MAIN_SEPARATOR, MAIN_SEPARATOR_STR};
use std::sync::mpsc;
use std::{fs, thread};
use ustr::{ustr, Ustr};

pub struct ModuleGraph {
    // input map of python import path to toplevel package path
    source_roots: HashMap<String, String>, // fs->py
    import_roots: HashMap<String, String>, // py->fs

    global_prefixes: HashSet<String>,
    local_prefixes: HashSet<String>,

    // import to track even without matching code
    // most useful to track importlib and __import___
    external_prefixes: MatcherNode,

    // prefix matching for package import/package paths
    import_matcher: MatcherNode,
    package_matcher: MatcherNode,

    modules_refs: LockedModuleRefCache,
    dir_cache: DashMap<String, HashSet<String>>,

    // collected imports
    global_ns: DashMap<ModuleRef, HashSet<ModuleRef>>,
    unresolved: DashMap<Ustr, HashSet<ModuleRef>>,
}

fn root_namespace(name: &str) -> &str {
    match name.find('.') {
        Some(idx) => &name[..idx],
        None => name,
    }
}

impl ModuleGraph {
    pub fn new(
        source_roots: HashMap<String, String>,
        global_prefixes: HashSet<String>,
        local_prefixes: HashSet<String>,
        external_prefixes: HashSet<String>,
    ) -> ModuleGraph {
        ModuleGraph {
            // NB: exclude local ns from import matcher
            import_matcher: MatcherNode::from(
                source_roots
                    .values()
                    .filter(|v| global_prefixes.contains(root_namespace(v))),
                '.',
            ),
            package_matcher: MatcherNode::from(source_roots.keys(), MAIN_SEPARATOR),
            // reverse, ignoring local
            import_roots: HashMap::from_iter(source_roots.iter().filter_map(|(k, v)| {
                if global_prefixes.contains(root_namespace(v)) {
                    Some((v.clone(), k.clone()))
                } else {
                    None
                }
            })),
            source_roots,
            global_prefixes,
            local_prefixes,
            external_prefixes: MatcherNode::from(external_prefixes, '.'),
            modules_refs: LockedModuleRefCache::new(),
            dir_cache: DashMap::new(),
            global_ns: DashMap::new(),
            unresolved: DashMap::new(),
        }
    }

    fn is_local(&self, name: &str) -> Option<bool> {
        let ns = root_namespace(name);
        if self.local_prefixes.contains(ns) {
            Some(true)
        } else if self.global_prefixes.contains(ns) {
            Some(false)
        } else {
            None
        }
    }

    pub fn add<T: IntoIterator<Item = String>>(
        &self,
        filepath: &str,
        pkg: &str,
        module: &str,
        deps: T,
        is_ns_pkg_init: bool,
    ) {
        let is_local = match self.is_local(module) {
            None => {
                warn!("module {} not local {}", module, filepath);
                return;
            }
            Some(local) => local,
        };

        // holy shittastic batman!
        // what if you have foo.py next to foo/__init__.py ?
        // Python will preferentially pick the package over the module, and so should we
        // NB: this is important to enforce unique mapping of import path to ModuleRef
        let parent = &filepath[..filepath.rfind('.').unwrap()];
        if self.exists_case_sensitive(parent, "__init__.py")
            || self.exists_case_sensitive(parent, "__init__.pyi")
        {
            warn!("ignoring {} in favor of conflicting package", filepath);
            return;
        }

        let mut unresolved = HashSet::new();
        let mut imports = HashSet::new();

        for dep in deps {
            let pref = self.external_prefixes.longest_prefix(&dep, '.');
            if !pref.is_empty() {
                imports.insert(self.modules_refs.get_or_create(ustr(""), ustr(pref), None));
                continue;
            } else if dep.ends_with(".*") {
                // NB: per python spec, star import only import submodules that are referenced in
                // the __all__ variable set in a package's __init__.py
                // Handling that accurately would require:
                //  - evaluating __all__ which would necessarily have to rely on heuristics since
                //    it could in theory be touched with arbitrary code, because that's how Python
                //    rolls
                //  - tracking the value of __all__ for all packages
                //  - deferring resolution of * imports until the relevant package is parsed and
                //    its __all__ value is known
                //
                // This is a tremendous amount of complexity for relatively little value. Instead,
                // we can do something much easier: act as if __all__ contained all the submodules
                // present on the filesystem.
                // This might result in spurious additional dependencies, but it cannot possibly
                // result in missed dependencies, and we're more concerned about false negatives
                // than false positives.
                // These "spurious" additional deps are in fact a feature, as it allows us to
                // concisely inform the parser of some programmatically inserted dependencies
                let target = &dep[..dep.len() - 2];
                if let Some(refs) = self.to_module_list_local_aware(pkg, ustr(target)) {
                    debug!("star: {} {} {:?}", filepath, dep, refs);
                    refs.iter().for_each(|r| {
                        imports.insert(*r);
                    });
                }
            } else if let Some(dep_ref) = self.to_module_local_aware(pkg, ustr(&dep)) {
                imports.insert(dep_ref);
            } else if self.is_local(&dep).is_some() {
                // record relevant imports that cannot be resolved
                // NB: if resolution failed, we know that we also fail to find the parent
                // so record that, to reduce noise from many function/classes from a single
                // unresolved module
                if let Some(idx) = dep.rfind('.') {
                    info!("unresolved: {} {} {}", filepath, dep, &dep[..idx]);
                    unresolved.insert(ustr(&dep[..idx]));
                }
            }
        }

        let nspkg = is_ns_pkg_init || self.import_matcher.strict_prefix(module, '.');
        let module_ref = if nspkg && !is_local {
            // __init__.py for a namespace package
            // should be empty except for the '__path__ = ...' stanza
            // we need to create a single ModuleRef for each of these, without link
            // to any of the actual file paths, otherwise the graph becomes unstable
            // and its shape changes with the order in which imports are found...
            self.modules_refs
                .get_or_create(ustr(""), ustr(module), None)
        } else {
            let module = ustr(module);
            let filepath = ustr(filepath);
            if is_local {
                for &d in &imports {
                    let dv = self.modules_refs.get(d);
                    if let Some(dpkg) = dv.pkg {
                        if dpkg != pkg {
                            let a = dpkg.rsplit_once(MAIN_SEPARATOR);
                            let b = pkg.split_once(MAIN_SEPARATOR);
                            assert!(a.is_some() && b.is_some(), "{} {}", dpkg, pkg);
                            // relaxed neighbor check
                            assert_eq!(a.unwrap().0, b.unwrap().0,);
                        }
                    }
                }
                self.modules_refs
                    .get_or_create(filepath, module, Some(ustr(pkg)))
            } else {
                self.modules_refs.get_or_create(filepath, module, None)
            }
        };
        for un in unresolved {
            self.unresolved.entry(un).or_default().insert(module_ref);
        }
        debug!(
            "parsed imports: {} {} {} {}",
            filepath,
            module,
            module_ref,
            imports.len()
        );
        if nspkg && self.global_ns.contains_key(&module_ref) {
            // for the weird, rare case where ns pkg init has some imports, need to merge
            self.global_ns.get_mut(&module_ref).unwrap().extend(imports);
        } else {
            self.global_ns.insert(module_ref, imports);
        }
    }

    fn exists_case_sensitive(&self, dir: &str, name: &str) -> bool {
        // Oh joy! on case-insensitive filesystems we want to make sure we resolve
        // module paths in a way that is consistent with what Python itself does
        // as formalized in PEP 235 https://peps.python.org/pep-0235/
        // Is this really necessary? well, yes, because some people are fond of
        // re-exporting things in their __init__.py to allow for short and "pretty"
        // import that hide internal structure. So for instance
        // foo/
        //   __init__.py
        //   bar.py
        //
        // with bar.py:
        //      class Bar:
        //
        // and __init__.py:
        //      from .bar import Bar
        //
        // so that other files can do:
        //      from foo import Bar
        //
        // we want to resolve that last form into an import to foo.bar, not foo.Bar!
        //
        // Hence this case-sensitive existence check that works on case-preserving
        // filesystems by listing the contents of the parent directory to confirm
        // a match

        // fast path because readdir is expensive
        if !fs::exists(dir.to_string() + MAIN_SEPARATOR_STR + name).unwrap_or(false) {
            return false;
        }
        // use a cache of directory listings, because readdir is expensive
        match self.dir_cache.entry(dir.to_string()) {
            Entry::Vacant(e) => match fs::read_dir(dir) {
                Err(_) => false,
                Ok(entries) => {
                    let mut children = HashSet::new();
                    for e in entries {
                        children.insert(e.unwrap().file_name().to_str().unwrap().to_string());
                    }
                    let exists = children.contains(name);
                    e.insert(children);
                    exists
                }
            },
            Entry::Occupied(e) => e.get().contains(name),
        }
    }

    fn to_module_no_cache(
        &self,
        mut dep: Ustr,
        fs_candidate: &str,
        local_fs_root: Option<Ustr>,
    ) -> Option<ModuleRef> {
        // the target of an import statement could be a module, or a value within that module
        // we only want to deal with modules when building an import graph, so we check if a
        // module path resolves to a file, and omit the final component if we can prove it
        // isn't a valid module

        if self.import_matcher.strict_prefix(dep.as_str(), '.') {
            // namespace packages FTW
            return Some(self.modules_refs.get_or_create(ustr(""), dep, None));
        }

        let mut depbase = fs_candidate.to_string();
        for _ in 0..2 {
            let _init_pyi = &(depbase.clone() + MAIN_SEPARATOR_STR + "__init__.pyi");
            let _init_py = &_init_pyi[.._init_pyi.len() - 1];
            let _mod_pyi = &(depbase.clone() + ".pyi");
            let _mod_pyx = &(depbase.clone() + ".pyx");
            let _mod_py = &_mod_pyi[.._mod_pyi.len() - 1];

            let candidate_init_pyi = ustr(_init_pyi);
            let candidate_init_py = ustr(_init_py);
            let candidate_module_pyi = ustr(_mod_pyi);
            let candidate_module_pyx = ustr(_mod_pyx);
            let candidate_module_py = ustr(_mod_py);

            if let Some(r) = self
                .modules_refs
                .ref_for_fs(candidate_init_py)
                .or_else(|| self.modules_refs.ref_for_fs(candidate_init_pyi))
                .or_else(|| self.modules_refs.ref_for_fs(candidate_module_py))
                .or_else(|| self.modules_refs.ref_for_fs(candidate_module_pyx))
                .or_else(|| self.modules_refs.ref_for_fs(candidate_module_pyi))
            {
                let rv = self.modules_refs.get(r);
                assert_eq!(rv.pkg, local_fs_root);
                return Some(r);
            }

            for cand in [
                candidate_init_py,
                candidate_init_pyi,
                candidate_module_py,
                candidate_module_pyx,
                candidate_module_pyi,
            ] {
                if let Some((dir, name)) = cand.rsplit_once(MAIN_SEPARATOR) {
                    if self.exists_case_sensitive(dir, name) {
                        return Some(self.modules_refs.get_or_create(cand, dep, local_fs_root));
                    }
                }
            }

            // if at first you don't succeed remove the last component and try again
            // TODO: for correctness we should distinguish between simple import and from import
            // as this fallback is only valid for the latter...
            if let Some(idx) = dep.rfind('.') {
                depbase = depbase[..depbase.len() - dep.len() + idx].to_string();
                dep = ustr(&dep[..idx]);
            } else {
                break;
            }
        }
        if let Some(_is_local) = self.is_local(dep.as_str()) {
            // TODO: would be nice to report where from
            debug!("{} not found around {}", dep, fs_candidate);
        }
        None
    }

    fn to_module_local_aware(&self, fs_root: &str, dep: Ustr) -> Option<ModuleRef> {
        if self.import_matcher.strict_prefix(dep.as_str(), '.') {
            // namespace packages FTW
            return Some(self.modules_refs.get_or_create(ustr(""), dep, None));
        }
        match self.py_to_fs(&dep, fs_root) {
            Some((fs_cand, local_fs_root)) => self.to_module_no_cache(dep, &fs_cand, local_fs_root),
            None => None,
        }
    }

    fn to_module_list(
        &self,
        fs_cand: String,
        dep: Ustr,
        local_fs_root: Option<Ustr>,
    ) -> Option<Vec<ModuleRef>> {
        let r = self.to_module_no_cache(dep, &fs_cand, local_fs_root);
        match fs::read_dir(&fs_cand) {
            Err(_) => r.map(|r| vec![r]),
            Ok(entries) => Some(
                entries
                    .filter_map(|entry| match entry {
                        Err(_) => None,
                        Ok(e) => {
                            let t = e.file_type().unwrap();
                            let name = e.file_name().to_str().unwrap().to_string();
                            if t.is_dir() {
                                if fs::exists(e.path().join("__init__.py")).unwrap_or(false)
                                    || fs::exists(e.path().join("__init__.pyi")).unwrap_or(false)
                                    || fs::exists(e.path().join("__init__.pyx")).unwrap_or(false)
                                {
                                    Some(name)
                                } else {
                                    None
                                }
                            } else if !t.is_file() {
                                None
                            } else if name.ends_with(".py") && name != "__init__.py" {
                                Some(name[..name.len() - 3].to_string())
                            } else if (name.ends_with(".pyi") && name != "__init__.pyi")
                                || (name.ends_with(".pyx") && name != "__init__.pyx")
                            {
                                // NB: there might be a duplicate if there is a matching *.py
                                // however that will be fine downstream as we only ever use
                                // this list to populate a set of ModuleRef...
                                Some(name[..name.len() - 4].to_string())
                            } else {
                                None
                            }
                        }
                    })
                    .filter_map(|sub| {
                        let subdep = dep.to_string() + "." + &sub;
                        self.to_module_no_cache(
                            ustr(&subdep),
                            &(fs_cand.clone() + MAIN_SEPARATOR_STR + &sub),
                            local_fs_root,
                        )
                    })
                    .chain(r.map_or(Vec::default(), |r| vec![r]))
                    .collect(),
            ),
        }
    }

    fn to_module_list_local_aware(&self, pkg: &str, dep: Ustr) -> Option<Vec<ModuleRef>> {
        match self.py_to_fs(&dep, pkg) {
            Some((fs_cand, local_fs_root)) => self.to_module_list(fs_cand, dep, local_fs_root),
            None => None,
        }
    }

    pub fn parse_parallel(&self, include_typechecking: bool) -> Result<(), anyhow::Error> {
        let parallelism = thread::available_parallelism().unwrap().get();

        let mut package_it = self.source_roots.keys();
        let builder = &mut WalkBuilder::new(package_it.next().unwrap());
        for a in package_it {
            builder.add(a);
        }

        let mut prefixes: HashSet<String> = HashSet::new();
        self.global_prefixes.iter().for_each(|n| {
            prefixes.insert(n.clone());
        });
        self.local_prefixes.iter().for_each(|n| {
            prefixes.insert(n.clone());
        });

        let (tx, rx) = mpsc::channel::<anyhow::Error>();

        // NB: we have to disable handling of .gitignore because
        // some real smart folks have ignore patterns that match
        // files that are committed in the repo...
        builder
            .standard_filters(false)
            .hidden(true)
            .threads(parallelism)
            .build_parallel()
            .run(|| {
                let tx = tx.clone();
                Box::new(move |r| match r {
                    Err(err) => {
                        tx.send(match err {
                            Error::WithPath { ref path, err } => err
                                .io_error()
                                .with_context(|| format!("failed to walk {}", path.display()))
                                .err()
                                .unwrap(),
                            _ => err.io_error().with_context(|| "").err().unwrap(),
                        })
                        .unwrap();
                        WalkState::Quit
                    }
                    Ok(e) => self.parse_one_file(e, include_typechecking, &tx),
                })
            });

        drop(tx);

        let mut res = Ok(());
        // check for errors during the walk
        for err in rx.iter() {
            error!("{}", err);
            if res.is_ok() {
                // NB: we only return the first one...
                res = Err(err);
            }
        }
        res
    }

    /// Map an arbitrary file path to a matching source root, if possible
    fn fs_to_py<'a>(&self, filepath: &'a str) -> Option<(&'a str, String)> {
        let fs_root_candidate = self
            .package_matcher
            .longest_prefix(filepath, MAIN_SEPARATOR);
        let py_root = self.source_roots.get(fs_root_candidate);
        py_root?;
        Some((
            fs_root_candidate,
            // TODO: normalize '-' and '.' in module name to '_' ?
            // NB: would require being able to denormalize in py_to_fs...
            py_root.unwrap().to_string()
                + &filepath[fs_root_candidate.len()..].replace(MAIN_SEPARATOR, "."),
        ))
    }

    /// map an arbitrary python import path to a matching source root
    fn py_to_fs(&self, import_path: &str, fs_root: &str) -> Option<(String, Option<Ustr>)> {
        match self.is_local(import_path) {
            None => None,
            Some(true) => {
                let py_root = self.source_roots.get(fs_root).unwrap();
                // local namespace can only be reached from itself or its neighbors
                if import_path.starts_with(py_root) {
                    Some((
                        fs_root.to_string()
                            + &import_path[py_root.len()..].replace('.', MAIN_SEPARATOR_STR),
                        Some(ustr(fs_root)),
                    ))
                } else {
                    let neighbor = fs_root[..fs_root.len() - py_root.len()].to_string()
                        + root_namespace(import_path);
                    if let Some(py_root) = self.source_roots.get(&neighbor) {
                        let local_fs_root = ustr(&neighbor);
                        Some((
                            neighbor
                                + &import_path[py_root.len()..].replace('.', MAIN_SEPARATOR_STR),
                            Some(local_fs_root),
                        ))
                    } else {
                        None
                    }
                }
            }
            Some(false) => {
                let py_root = self.import_matcher.longest_prefix(import_path, '.');
                self.import_roots.get(py_root).map(|dst_root| {
                    (
                        dst_root.to_string()
                            + &import_path[py_root.len()..].replace('.', MAIN_SEPARATOR_STR),
                        None,
                    )
                })
            }
        }
    }

    fn parse_one_file(
        &self,
        e: DirEntry,
        include_typechecking: bool,
        _tx: &mpsc::Sender<anyhow::Error>,
    ) -> WalkState {
        let filepath = e.path().to_str().unwrap();
        if filepath.ends_with(".py") {
            // normal case: plain python code
        } else if (filepath.ends_with(".pyx") || filepath.ends_with(".pyi"))
            && !fs::exists(&filepath[..filepath.len() - 1]).unwrap_or(true)
        {
            // process .pyi / .pyx if and only if there isn't a corresponding .py
            // this is useful to handle native code, or generated code that
            // is not part of normal source tree, but that might still have
            // relevant dependency information

            // give precedence to pyx over pyi if both are present
            if filepath.ends_with("i")
                && fs::exists(&(filepath[..filepath.len() - 1].to_string() + "x")).unwrap_or(false)
            {
                return WalkState::Continue;
            }
            info!("info: allowing {}", filepath);
        } else {
            return WalkState::Continue;
        }
        debug!("parse: {}", filepath);
        let res = self.fs_to_py(filepath);
        if res.is_none() {
            return WalkState::Continue;
        }
        let (pkg, module) = res.unwrap();

        // remove .py[i|x] suffix, turn / into .
        // NB: preserve __init__ for correct relative import resolution
        let suffix_idx = module.rfind('.').unwrap();
        let module = module[..suffix_idx].replace(MAIN_SEPARATOR, ".");

        match raw_get_all_imports(filepath, &module, true, include_typechecking) {
            Ok((is_ns_pkg_init, imports)) => {
                // rip out the __init__ bit now that we've dealt with any relative imports
                let mut module: &str = &module;
                if module.ends_with(".__init__") {
                    module = &module[..module.len() - 9];
                }
                self.add(filepath, pkg, module, imports, is_ns_pkg_init);
                WalkState::Continue
            }
            Err(err) => {
                warn!("{}: {}", filepath, err);
                // which parse errors should abort the creation of the import graph?
                //tx.send(err).unwrap();
                WalkState::Continue
            }
        }
    }

    fn module_or_parent(&self, m: &str) -> Option<ModuleRef> {
        if let Some(r) = self.modules_refs.ref_for_py(ustr(m), None) {
            Some(r)
        } else if let Some((parent, _)) = m.rsplit_once('.') {
            self.modules_refs.ref_for_py(ustr(parent), None)
        } else {
            None
        }
    }

    pub fn add_dynamic_dependencies(&self, dynamic_edges: HashMap<String, HashSet<String>>) {
        for (m, deps) in dynamic_edges {
            if let Some(r) = self.modules_refs.first_matching_ref(ustr(&m)) {
                debug!("dynamic dep: {} -> {} +{:?}", m, r, deps);
                self.add_dynamic_dep(r, deps);
            } else {
                warn!("dynamic dep: {} not found", m);
            }
        }
    }

    fn add_dynamic_dep(&self, r: ModuleRef, deps: HashSet<String>) {
        // NB: insert a new set of deps if none exits
        // this is necessary to allow attaching dynamic deps to external imports
        let mut cur_deps = self.global_ns.entry(r).or_default();
        deps.iter().for_each(|dep| {
            if dep.ends_with(".*") {
                let dep_prefix = &dep[..dep.len() - 1];
                info!("dynamic wildcard: {}", dep_prefix);
                // TODO: more efficient prefix search?
                // probably overkill for now...
                for mod_ref in 0..self.modules_refs.max_value() {
                    let mod_py = self.modules_refs.py_for_ref(mod_ref);
                    if let Some(suffix) = mod_py.strip_prefix(dep_prefix) {
                        if !suffix.contains('.') {
                            info!(" > wildcard match: {}", mod_py);
                            cur_deps.insert(mod_ref);
                        }
                    }
                }
            } else if let Some(mod_ref) = self.module_or_parent(dep) {
                cur_deps.insert(mod_ref);
            }
        })
    }

    pub fn finalize(self) -> TransitiveClosure {
        let mut module_refs = self.modules_refs.take();
        reify_deps(&self.global_ns, &mut module_refs);
        let mut unresolved = HashMap::with_capacity(self.unresolved.len());
        for (k, v) in self.unresolved {
            unresolved.insert(k, v);
        }
        TransitiveClosure::from(&self.global_ns, module_refs, unresolved)
    }
}

fn reify_deps(g: &DashMap<ModuleRef, HashSet<ModuleRef>>, ref_cache: &mut ModuleRefCache) {
    // because of the way python import machinery works, namely executing top-level
    // statements in a module body, and the existence of __init__.py:
    //
    //  - import x.y.x implies a dep on x and x.y, not just x.y.z
    //
    // NB: this must happen after the whole graph is constructed to work correctly
    // NB: we construct missing namespace packages if needed

    ref_cache.validate();

    let mut n: ModuleRef = 0;
    while n < ref_cache.max_value() {
        let mut deps = g.entry(n).or_default();
        // add dep on all parent __init__.py
        let module = ref_cache.get(n);
        let mut idx = module.py.rfind('.');
        while idx.is_some() {
            let parent = ustr(&module.py[..idx.unwrap()]);
            let pref = ref_cache
                .ref_for_py(parent, module.pkg)
                // create ref for implicit namespace package
                // we need this because Python will create implicit namespaces,
                // and they will show up in the import tracker when validating
                .unwrap_or_else(|| ref_cache.get_or_create(ustr(""), parent, module.pkg));
            let pmod = ref_cache.get(pref);
            assert_eq!(pmod.pkg, module.pkg);
            deps.insert(pref);
            idx = parent.rfind('.');
        }
        n += 1;
    }
}
