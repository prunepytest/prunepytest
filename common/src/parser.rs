// SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

use regex::Regex;
use ruff_python_ast::visitor::source_order::{walk_expr, walk_stmt, SourceOrderVisitor};
use ruff_python_ast::{Expr, Stmt};
use ruff_python_parser::{parse_module, ParseError};
use ruff_text_size::Ranged;
use std::fmt::Display;
use std::fs::read_to_string;
use std::sync::LazyLock;
use std::{fs, io};

#[derive(Debug)]
pub enum Error {
    IO(io::Error),
    Parse(ParseError),
}

impl Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::IO(io) => io.fmt(f),
            Error::Parse(parse) => parse.fmt(f),
        }
    }
}

pub fn split_at_depth(filepath: &'_ str, sep: char, depth: usize) -> (&'_ str, &'_ str) {
    let mut idx: usize = filepath.len();
    let mut depth: usize = depth;
    while depth != 0 {
        match filepath[..idx].rfind(sep) {
            Some(next_idx) => {
                idx = next_idx;
                depth -= 1;
            }
            None => {
                panic!("{} @ {} {}", filepath, sep, depth);
            }
        }
    }
    (&filepath[0..idx], &filepath[idx + 1..])
}

struct ImportExtractor<'a> {
    source: &'a str,
    module: &'a str,
    deep: bool,
    include_typechecking: bool,

    imports: Vec<String>,
}

impl<'a> ImportExtractor<'a> {
    fn new(
        source: &'a str,
        module: &'a str,
        deep: bool,
        include_typechecking: bool,
    ) -> ImportExtractor<'a> {
        ImportExtractor {
            source,
            module,
            deep,
            include_typechecking,
            imports: Vec::new(),
        }
    }
}

impl<'b> SourceOrderVisitor<'b> for ImportExtractor<'_> {
    fn visit_stmt(&mut self, stmt: &'b Stmt) {
        if let Some(imp) = stmt.as_import_stmt() {
            for n in &imp.names {
                self.imports.push(n.name.to_string());
            }
        } else if let Some(imp) = stmt.as_import_from_stmt() {
            let mut target = String::new();
            if imp.level > 0 {
                let (parent, _) = split_at_depth(self.module, '.', imp.level as usize);
                target.push_str(parent);
            }
            if imp.module.is_some() {
                if !target.is_empty() {
                    target.push('.');
                }
                target.push_str(imp.module.as_ref().unwrap().as_str());
            }
            self.imports.push(target.clone());
            for n in &imp.names {
                self.imports.push(target.clone() + "." + n.name.as_str());
            }
        } else if self.deep {
            if let Some(if_stmt) = stmt.as_if_stmt() {
                // quick and dirty: skip if TYPE_CHECKING / if typing.TYPE_CHECKING
                // TODO: for added robustness:
                //  - keep track of imports from typing package
                //  - extract identifier from if condition and compare to imported symbol
                let range = if_stmt.test.range();
                let cond = &self.source[range.start().to_usize()..range.end().to_usize()];
                if (cond == "TYPE_CHECKING" || cond == "typing.TYPE_CHECKING")
                    && !self.include_typechecking
                {
                    // skip walking under
                    return;
                }
            }
            walk_stmt(self, stmt);
        }
    }

    fn visit_expr(&mut self, expr: &'b Expr) {
        if let Some(name) = expr.as_name_expr() {
            // special handling of references to __import__
            // this is done to allow flagging of dynamic imports that bypass importlib
            if name.id.as_str() == "__import__" {
                // could be:
                //      builtins.__import__ (which does not require an import)
                //      importlib.__import__
                self.imports.push("__import__".to_string());
            }
        }
        walk_expr(self, expr);
    }

    fn visit_body(&mut self, body: &'b [Stmt]) {
        for stmt in body {
            self.visit_stmt(stmt);
        }
    }
}

pub fn raw_imports_from_module<'a>(
    source: &'a str,
    module: &'a str,
    deep: bool,
    include_typechecking: bool,
) -> Result<Vec<String>, ParseError> {
    let m = parse_module(source)?;
    let mut extractor = ImportExtractor::new(source, module, deep, include_typechecking);
    extractor.visit_body(&m.syntax().body);
    Ok(extractor.imports)
}

pub fn content_looks_like_pkgutil_ns_init(source: &str) -> bool {
    static RE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r#"^__path__ *= *__import__ *\(('pkgutil'|"pkgutil")\).extend_path *\( *__path__ *, *__name__ *\)"#
        ).unwrap()
    });

    RE.is_match_at(source, 0)
}

pub fn file_looks_like_pkgutil_ns_init(filepath: &str) -> Result<bool, Error> {
    Ok(filepath.ends_with("__init__.py")
        && fs::exists(filepath).unwrap_or(false)
        && content_looks_like_pkgutil_ns_init(&read_to_string(filepath).map_err(Error::IO)?))
}

pub fn raw_get_all_imports(
    filepath: &str,
    module: &str,
    deep: bool,
    include_typechecking: bool,
) -> Result<(bool, Vec<String>), Error> {
    let source = read_to_string(filepath).map_err(Error::IO)?;
    Ok((
        filepath.ends_with("__init__.py") && content_looks_like_pkgutil_ns_init(&source),
        raw_imports_from_module(&source, module, deep, include_typechecking)
            .map_err(Error::Parse)?,
    ))
}
