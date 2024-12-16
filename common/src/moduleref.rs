// SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

use speedy::private::{read_length_u64_varint, write_length_u64_varint};
use speedy::{Context, Readable, Reader, Writable, Writer};
use std::collections::HashMap;
use std::path::MAIN_SEPARATOR;
use std::sync::RwLock;
use ustr::{ustr, Ustr};

pub type ModuleRef = u32;

#[derive(Debug, Clone, Copy)]
pub struct ModuleRefVal {
    pub(crate) fs: Ustr,
    pub(crate) py: Ustr,
    pub(crate) pkg: Option<Ustr>,
}

impl ModuleRefVal {
    fn new(fs: Ustr, py: Ustr, pkg: Option<Ustr>) -> ModuleRefVal {
        ModuleRefVal { fs, py, pkg }
    }
}

#[derive(Debug, Clone)]
pub struct ModuleRefCache {
    values: Vec<ModuleRefVal>,
    fs_to_ref: HashMap<Ustr, ModuleRef>,
    py_to_ref_global: HashMap<Ustr, ModuleRef>,
    py_to_ref_local: HashMap<Ustr, HashMap<Ustr, ModuleRef>>,
}

pub struct LockedModuleRefCache {
    inner: RwLock<ModuleRefCache>,
}

impl Default for LockedModuleRefCache {
    fn default() -> Self {
        Self::new()
    }
}

impl LockedModuleRefCache {
    pub fn new() -> LockedModuleRefCache {
        LockedModuleRefCache {
            inner: RwLock::new(ModuleRefCache {
                values: Vec::new(),
                fs_to_ref: HashMap::new(),
                py_to_ref_global: HashMap::new(),
                py_to_ref_local: HashMap::new(),
            }),
        }
    }

    pub fn take(self) -> ModuleRefCache {
        self.inner.into_inner().unwrap()
    }

    pub fn max_value(&self) -> ModuleRef {
        self.inner.read().unwrap().max_value()
    }

    pub fn get(&self, r: ModuleRef) -> ModuleRefVal {
        self.inner.read().unwrap().get(r)
    }

    pub fn py_for_ref(&self, r: ModuleRef) -> Ustr {
        self.inner.read().unwrap().py_for_ref(r)
    }
    pub fn fs_for_ref(&self, r: ModuleRef) -> Ustr {
        self.inner.read().unwrap().fs_for_ref(r)
    }
    pub fn pkg_for_ref(&self, r: ModuleRef) -> Option<Ustr> {
        self.inner.read().unwrap().pkg_for_ref(r)
    }

    pub fn first_matching_ref(&self, m: Ustr) -> Option<ModuleRef> {
        self.inner.read().unwrap().first_matching_ref(m)
    }

    pub fn ref_for_py(&self, py: Ustr, pkg: Option<Ustr>) -> Option<ModuleRef> {
        self.inner.read().unwrap().ref_for_py(py, pkg)
    }

    pub fn ref_for_fs(&self, fs: Ustr) -> Option<ModuleRef> {
        self.inner.read().unwrap().ref_for_fs(fs)
    }

    pub fn get_or_create(&self, fs: Ustr, py: Ustr, pkg: Option<Ustr>) -> ModuleRef {
        self.inner.write().unwrap().get_or_create(fs, py, pkg)
    }
}

impl ModuleRefCache {
    fn from_values(values: Vec<ModuleRefVal>) -> Self {
        let mut fs_to_ref = HashMap::new();
        let mut py_to_ref_global = HashMap::new();
        let mut py_to_ref_local: HashMap<Ustr, HashMap<Ustr, ModuleRef>> = HashMap::new();
        for (i, v) in values.iter().enumerate() {
            if !v.fs.is_empty() {
                fs_to_ref.insert(v.fs, i as ModuleRef);
            }
            match v.pkg {
                None => py_to_ref_global.insert(v.py, i as ModuleRef),
                Some(pkg) => py_to_ref_local
                    .entry(pkg)
                    .or_default()
                    .insert(v.py, i as ModuleRef),
            };
        }
        Self {
            values,
            fs_to_ref,
            py_to_ref_global,
            py_to_ref_local,
        }
    }

    pub fn max_value(&self) -> ModuleRef {
        self.values.len() as ModuleRef
    }

    pub fn get(&self, r: ModuleRef) -> ModuleRefVal {
        self.values[r as usize]
    }

    pub fn py_for_ref(&self, r: ModuleRef) -> Ustr {
        self.values[r as usize].py
    }
    pub fn fs_for_ref(&self, r: ModuleRef) -> Ustr {
        self.values[r as usize].fs
    }
    pub fn pkg_for_ref(&self, r: ModuleRef) -> Option<Ustr> {
        self.values[r as usize].pkg
    }

    pub fn first_matching_ref(&self, m: Ustr) -> Option<ModuleRef> {
        self.ref_for_fs(m)
            .or_else(|| self.ref_for_py(m, None))
            .or_else(|| {
                for refs in self.py_to_ref_local.values() {
                    if let Some(&x) = refs.get(&m) {
                        return Some(x);
                    }
                }
                None
            })
    }

    pub fn ref_for_py(&self, py: Ustr, pkg: Option<Ustr>) -> Option<ModuleRef> {
        match pkg {
            Some(pkg) => Some(*self.py_to_ref_local.get(&pkg)?.get(&py)?),
            None => Some(*self.py_to_ref_global.get(&py)?),
        }
    }

    pub fn ref_for_fs(&self, fs: Ustr) -> Option<ModuleRef> {
        Some(*self.fs_to_ref.get(&fs)?)
    }

    pub fn get_or_create(&mut self, fs: Ustr, py: Ustr, pkg: Option<Ustr>) -> ModuleRef {
        assert!(!py.contains(MAIN_SEPARATOR), "{} {}", fs, py);
        if fs.is_empty() {
            // namespace package, either implicit or explicit
            // since there can be multiple __init__.py, we don't record any
            if let Some(&r) = match pkg {
                None => self.py_to_ref_global.get(&py),
                Some(p) => self.py_to_ref_local.get(&p).and_then(|m| m.get(&py)),
            } {
                return r;
            }
        } else if let Some(&r) = self.fs_to_ref.get(&fs) {
            assert_eq!(self.values[r as usize].pkg, pkg);
            assert_eq!(self.values[r as usize].py, py);
            return r;
        } else if let Some(r) = self.ref_for_py(py, pkg) {
            let rfs = self.values[r as usize].fs;
            // we don't want hard mismatch here, but we allow soft mismatch for
            // weird cases where a namespace package has sibling modules
            assert!(
                rfs.is_empty() || rfs == fs,
                "{} {} {:?} {}",
                py,
                fs,
                pkg,
                rfs
            );
            return r;
        }

        let rv = ModuleRefVal::new(fs, py, pkg);
        let r = self.values.len() as ModuleRef;
        self.values.push(rv);
        if !fs.is_empty() {
            self.fs_to_ref.insert(fs, r);
        }
        match pkg {
            Some(pkg) => {
                let d = self.py_to_ref_local.entry(pkg).or_default();
                assert!(!d.contains_key(&py));
                d.insert(py, r)
            }
            None => {
                assert!(
                    !self.py_to_ref_global.contains_key(&py),
                    "{} {} {:?}",
                    py,
                    fs,
                    self.values[*self.py_to_ref_global.get(&py).unwrap() as usize]
                );
                self.py_to_ref_global.insert(py, r)
            }
        };
        r
    }

    pub fn validate(&self) {
        for r in 0..self.values.len() {
            let rv = &self.values[r];
            if !rv.fs.is_empty() {
                assert_eq!(self.ref_for_fs(rv.fs), Some(r as ModuleRef));
            }
            assert_eq!(
                self.ref_for_py(rv.py, rv.pkg),
                Some(r as ModuleRef),
                "{} {:?}",
                rv.py,
                rv.pkg
            );
        }
    }
}

impl<C> Writable<C> for ModuleRefVal
where
    C: Context,
{
    fn write_to<T: ?Sized + Writer<C>>(&self, writer: &mut T) -> Result<(), C::Error> {
        write_ustr_to(self.fs, writer)
            .and_then(|_| write_ustr_to(self.py, writer))
            .and_then(|_| write_ustr_to(self.pkg.unwrap_or_default(), writer))
    }
}

pub(crate) fn write_ustr_to<C: Context, T: ?Sized + Writer<C>>(
    s: Ustr,
    writer: &mut T,
) -> Result<(), C::Error> {
    write_length_u64_varint(s.len(), writer).and_then(|_| writer.write_bytes(s.as_bytes()))
}

pub(crate) fn read_ustr_with_buf<'a, C: Context, R: Reader<'a, C>>(
    reader: &mut R,
    buf: &mut Vec<u8>,
) -> Result<Ustr, C::Error> {
    buf.resize(read_length_u64_varint(reader)?, 0);
    reader.read_bytes(buf.as_mut_slice())?;
    Ok(ustr(std::str::from_utf8(buf.as_slice()).map_err(|e| {
        speedy::Error::custom(format!("{:?} {:?}", e, buf))
    })?))
}

impl<'a, C> Readable<'a, C> for ModuleRefVal
where
    C: Context,
{
    fn read_from<R: Reader<'a, C>>(reader: &mut R) -> Result<Self, C::Error> {
        let mut buf: Vec<u8> = Vec::new();
        let fs = read_ustr_with_buf(reader, &mut buf)?;
        let py = read_ustr_with_buf(reader, &mut buf)?;
        let pkg = read_ustr_with_buf(reader, &mut buf)?;
        let pkg = match pkg.len() {
            0 => None,
            _ => Some(pkg),
        };
        Ok(ModuleRefVal { fs, py, pkg })
    }

    fn minimum_bytes_needed() -> usize {
        3
    }
}

impl<C> Writable<C> for ModuleRefCache
where
    C: Context,
{
    fn write_to<T: ?Sized + Writer<C>>(&self, writer: &mut T) -> Result<(), C::Error> {
        let g = &self.values;
        write_length_u64_varint(g.len(), writer)?;
        for v in g.iter() {
            writer.write_value(v)?;
        }
        Ok(())
    }
}

impl<'a, C> Readable<'a, C> for ModuleRefCache
where
    C: Context,
{
    fn read_from<R: Reader<'a, C>>(reader: &mut R) -> Result<Self, C::Error> {
        let sz = read_length_u64_varint(reader)?;
        let mut values = Vec::with_capacity(sz);
        for _ in 0..sz {
            values.push(reader.read_value::<ModuleRefVal>()?);
        }
        Ok(ModuleRefCache::from_values(values))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::MAIN_SEPARATOR_STR;

    #[test]
    fn get_or_create_global() {
        let mrc = LockedModuleRefCache::default();
        let r0 = mrc.get_or_create(ustr("foo/bar.py"), ustr("foo.bar"), None);
        let r1 = mrc.get_or_create(ustr("foo/baz.py"), ustr("foo.baz"), None);
        let r2 = mrc.get_or_create(ustr("qux.py"), ustr("qux"), None);

        assert!(r0 < mrc.max_value());
        assert!(r1 < mrc.max_value());
        assert!(r2 < mrc.max_value());
        assert_ne!(r0, r1);
        assert_ne!(r0, r2);
        assert_ne!(r1, r2);

        let max = mrc.max_value();

        assert_eq!(
            r0,
            mrc.get_or_create(ustr("foo/bar.py"), ustr("foo.bar"), None)
        );
        assert_eq!(
            r1,
            mrc.get_or_create(ustr("foo/baz.py"), ustr("foo.baz"), None)
        );
        assert_eq!(r2, mrc.get_or_create(ustr("qux.py"), ustr("qux"), None));

        assert_eq!(max, mrc.max_value());

        assert_eq!("foo/bar.py", mrc.fs_for_ref(r0));
        assert_eq!("foo/baz.py", mrc.fs_for_ref(r1));
        assert_eq!("qux.py", mrc.fs_for_ref(r2));

        assert_eq!("foo.bar", mrc.py_for_ref(r0));
        assert_eq!("foo.baz", mrc.py_for_ref(r1));
        assert_eq!("qux", mrc.py_for_ref(r2));

        assert_eq!(None, mrc.pkg_for_ref(r0));
        assert_eq!(None, mrc.pkg_for_ref(r1));
        assert_eq!(None, mrc.pkg_for_ref(r2));

        assert_eq!(Some(r0), mrc.ref_for_fs(ustr("foo/bar.py")));
        assert_eq!(Some(r1), mrc.ref_for_fs(ustr("foo/baz.py")));
        assert_eq!(Some(r2), mrc.ref_for_fs(ustr("qux.py")));
        assert_eq!(None, mrc.ref_for_fs(ustr("foo.bar")));
        assert_eq!(None, mrc.ref_for_fs(ustr("foo.baz")));
        assert_eq!(None, mrc.ref_for_fs(ustr("qux")));

        assert_eq!(None, mrc.ref_for_py(ustr("foo/bar.py"), None));
        assert_eq!(None, mrc.ref_for_py(ustr("foo/baz.py"), None));
        assert_eq!(None, mrc.ref_for_py(ustr("qux.py"), None));
        assert_eq!(Some(r0), mrc.ref_for_py(ustr("foo.bar"), None));
        assert_eq!(Some(r1), mrc.ref_for_py(ustr("foo.baz"), None));
        assert_eq!(Some(r2), mrc.ref_for_py(ustr("qux"), None));
        assert_eq!(None, mrc.ref_for_py(ustr("foo.bar"), Some(ustr("foo"))));
        assert_eq!(None, mrc.ref_for_py(ustr("foo.baz"), Some(ustr("foo"))));
        assert_eq!(None, mrc.ref_for_py(ustr("qux"), Some(ustr("foo"))));
    }

    #[test]
    fn get_or_create_local() {
        let mrc = LockedModuleRefCache::default();
        let r0 = mrc.get_or_create(ustr("a/foo.py"), ustr("foo"), Some(ustr("a")));
        let r1 = mrc.get_or_create(ustr("b/foo.py"), ustr("foo"), Some(ustr("b")));
        let r2 = mrc.get_or_create(ustr("c/foo.py"), ustr("foo"), None);

        assert!(r0 < mrc.max_value());
        assert!(r1 < mrc.max_value());
        assert!(r2 < mrc.max_value());
        assert_ne!(r0, r1);
        assert_ne!(r0, r2);
        assert_ne!(r1, r2);

        let max = mrc.max_value();

        assert_eq!(
            r0,
            mrc.get_or_create(ustr("a/foo.py"), ustr("foo"), Some(ustr("a")))
        );
        assert_eq!(
            r1,
            mrc.get_or_create(ustr("b/foo.py"), ustr("foo"), Some(ustr("b")))
        );
        assert_eq!(r2, mrc.get_or_create(ustr("c/foo.py"), ustr("foo"), None));

        assert_eq!(max, mrc.max_value());

        assert_eq!("a/foo.py", mrc.fs_for_ref(r0));
        assert_eq!("b/foo.py", mrc.fs_for_ref(r1));
        assert_eq!("c/foo.py", mrc.fs_for_ref(r2));

        assert_eq!("foo", mrc.py_for_ref(r0));
        assert_eq!("foo", mrc.py_for_ref(r1));
        assert_eq!("foo", mrc.py_for_ref(r2));

        assert_eq!(Some(ustr("a")), mrc.pkg_for_ref(r0));
        assert_eq!(Some(ustr("b")), mrc.pkg_for_ref(r1));
        assert_eq!(None, mrc.pkg_for_ref(r2));

        assert_eq!(Some(r0), mrc.ref_for_fs(ustr("a/foo.py")));
        assert_eq!(Some(r1), mrc.ref_for_fs(ustr("b/foo.py")));
        assert_eq!(Some(r2), mrc.ref_for_fs(ustr("c/foo.py")));
        assert_eq!(None, mrc.ref_for_fs(ustr("foo")));

        assert_eq!(None, mrc.ref_for_py(ustr("a/foo.py"), None));
        assert_eq!(None, mrc.ref_for_py(ustr("b/foo.py"), None));
        assert_eq!(None, mrc.ref_for_py(ustr("c/foo.py"), None));
        assert_eq!(Some(r0), mrc.ref_for_py(ustr("foo"), Some(ustr("a"))));
        assert_eq!(Some(r1), mrc.ref_for_py(ustr("foo"), Some(ustr("b"))));
        assert_eq!(Some(r2), mrc.ref_for_py(ustr("foo"), None));
        assert_eq!(None, mrc.ref_for_py(ustr("foo"), Some(ustr("c"))));
    }

    #[test]
    fn get_or_create_no_fs() {
        let mrc = LockedModuleRefCache::default();

        // namespace pkg may have the same py mapping to multiple fs value
        // to support that, we allow the fs value to be omitted
        let r0 = mrc.get_or_create(ustr(""), ustr("foo"), Some(ustr("a")));
        let r1 = mrc.get_or_create(ustr(""), ustr("foo"), Some(ustr("b")));
        let r2 = mrc.get_or_create(ustr(""), ustr("foo"), None);

        assert!(r0 < mrc.max_value());
        assert!(r1 < mrc.max_value());
        assert!(r2 < mrc.max_value());
        assert_ne!(r0, r1);
        assert_ne!(r0, r2);
        assert_ne!(r1, r2);

        let max = mrc.max_value();

        assert_eq!(
            r0,
            mrc.get_or_create(ustr(""), ustr("foo"), Some(ustr("a")))
        );
        assert_eq!(
            r1,
            mrc.get_or_create(ustr(""), ustr("foo"), Some(ustr("b")))
        );
        assert_eq!(r2, mrc.get_or_create(ustr(""), ustr("foo"), None));

        assert_eq!(max, mrc.max_value());

        assert_eq!("", mrc.fs_for_ref(r0));
        assert_eq!("", mrc.fs_for_ref(r1));
        assert_eq!("", mrc.fs_for_ref(r2));

        assert_eq!("foo", mrc.py_for_ref(r0));
        assert_eq!("foo", mrc.py_for_ref(r1));
        assert_eq!("foo", mrc.py_for_ref(r2));

        assert_eq!(Some(ustr("a")), mrc.pkg_for_ref(r0));
        assert_eq!(Some(ustr("b")), mrc.pkg_for_ref(r1));
        assert_eq!(None, mrc.pkg_for_ref(r2));

        assert_eq!(None, mrc.ref_for_fs(ustr("")));

        assert_eq!(None, mrc.ref_for_py(ustr(""), None));
        assert_eq!(Some(r0), mrc.ref_for_py(ustr("foo"), Some(ustr("a"))));
        assert_eq!(Some(r1), mrc.ref_for_py(ustr("foo"), Some(ustr("b"))));
        assert_eq!(Some(r2), mrc.ref_for_py(ustr("foo"), None));
        assert_eq!(None, mrc.ref_for_py(ustr("foo"), Some(ustr("c"))));
    }

    #[test]
    fn allow_mixed_fs() {
        let mrc = LockedModuleRefCache::default();
        let r0 = mrc.get_or_create(ustr(""), ustr("foo"), None);
        let r1 = mrc.get_or_create(ustr("foo.py"), ustr("foo"), None);

        assert_eq!(r0, r1);

        let r2 = mrc.get_or_create(ustr("bar.py"), ustr("bar"), None);
        let r3 = mrc.get_or_create(ustr(""), ustr("bar"), None);

        assert_eq!(r2, r3);
        assert_ne!(r0, r2);
    }

    #[test]
    #[should_panic]
    fn disallow_path_sep_in_py() {
        let mrc = LockedModuleRefCache::default();
        mrc.get_or_create(
            ustr(""),
            ustr(&("foo".to_string() + MAIN_SEPARATOR_STR + "bar")),
            None,
        );
    }

    #[test]
    #[should_panic]
    fn disallow_mismatch_pkg() {
        let mrc = LockedModuleRefCache::default();
        mrc.get_or_create(ustr("foo.py"), ustr("foo"), None);
        mrc.get_or_create(ustr("foo.py"), ustr("foo"), Some(ustr("foo")));
    }

    #[test]
    #[should_panic]
    fn disallow_mismatch_pkg_2() {
        let mrc = LockedModuleRefCache::default();
        mrc.get_or_create(ustr("foo.py"), ustr("foo"), Some(ustr("foo")));
        mrc.get_or_create(ustr("foo.py"), ustr("foo"), Some(ustr("bar")));
    }

    #[test]
    #[should_panic]
    fn disallow_mismatch_py_global() {
        let mrc = LockedModuleRefCache::default();
        mrc.get_or_create(ustr("foo.py"), ustr("foo"), None);
        mrc.get_or_create(ustr("foo.py"), ustr("bar"), None);
    }

    #[test]
    #[should_panic]
    fn disallow_mismatch_py_local() {
        let mrc = LockedModuleRefCache::default();
        mrc.get_or_create(ustr("foo.py"), ustr("foo"), Some(ustr("foo")));
        mrc.get_or_create(ustr("foo.py"), ustr("bar"), Some(ustr("foo")));
    }
}
