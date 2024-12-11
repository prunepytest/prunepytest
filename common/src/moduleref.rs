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
            assert!(pkg.is_none());
            if let Some(r) = self.py_to_ref_global.get(&py) {
                return *r;
            }
        } else if let Some(r) = self.fs_to_ref.get(&fs) {
            let mr = *r;
            assert_eq!(self.values[mr as usize].pkg, pkg);
            return mr;
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
