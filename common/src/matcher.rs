// SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

use std::collections::HashMap;

pub struct MatcherNode {
    is_leaf: bool,
    children: HashMap<String, MatcherNode>,
}

impl Default for MatcherNode {
    fn default() -> Self {
        Self::new()
    }
}

impl MatcherNode {
    pub fn new() -> MatcherNode {
        MatcherNode {
            is_leaf: false,
            children: HashMap::new(),
        }
    }

    pub fn from<V: AsRef<str>, T: IntoIterator<Item = V>>(values: T, sep: char) -> MatcherNode {
        let mut tree = Self::new();
        for val in values {
            tree.add(val.as_ref(), sep);
        }
        tree
    }

    pub fn add(&mut self, val: &str, sep: char) {
        let mut node = self;
        for p in val.split(sep) {
            if !node.children.contains_key(p) {
                node.children.insert(p.to_string(), MatcherNode::new());
            }
            node = node.children.get_mut(p).unwrap()
        }
        node.is_leaf = true;
    }

    pub fn matches(&self, value: &str, sep: char) -> bool {
        let mut n = self;
        for c in value.split(sep) {
            if n.is_leaf {
                return true;
            }
            match n.children.get(c) {
                None => return false,
                Some(m) => n = m,
            }
        }
        n.is_leaf
    }

    pub fn strict_prefix(&self, value: &str, sep: char) -> bool {
        let mut n = self;
        for c in value.split(sep) {
            match n.children.get(c) {
                None => return false,
                Some(m) => n = m,
            }
        }
        !n.is_leaf
    }

    pub fn longest_prefix_len(&self, value: &str, sep: char) -> usize {
        let mut n = self;
        let mut prefix_len: usize = 0;
        let mut idx: usize = 0;
        for c in value.split(sep) {
            match n.children.get(c) {
                None => return prefix_len,
                Some(m) => {
                    n = m;
                }
            }
            idx += c.len() + 1;
            if n.is_leaf {
                prefix_len = idx - 1
            }
        }
        prefix_len
    }

    pub fn longest_prefix<'a>(&self, value: &'a str, sep: char) -> &'a str {
        &value[..self.longest_prefix_len(value, sep)]
    }

    pub fn all_suffixes_of_into<S, T>(&self, value: &str, sep: char, res: &mut T)
    where
        S: From<String>,
        T: Extend<S>,
    {
        let mut n = self;
        for c in value.split(sep) {
            match n.children.get(c) {
                None => return,
                Some(m) => {
                    n = m;
                }
            }
        }
        n.all_suffixes_into(value, sep, res);
    }

    fn all_suffixes_into<S, T>(&self, prefix: &str, sep: char, res: &mut T)
    where
        S: From<String>,
        T: Extend<S>,
    {
        for (name, child) in &self.children {
            let mut cp = prefix.to_string();
            if !prefix.is_empty() {
                cp.push(sep);
            }
            cp.push_str(name);
            if child.is_leaf {
                res.extend(Some(S::from(cp.clone())));
            }
            child.all_suffixes_into(&cp, sep, res);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn from_values() {
        let m = MatcherNode::from(
            vec![
                "foo",
                "bar/v1",
                "bar/v2",
                "qux/a",
                "qux/a/sub",
                "qux/b",
                "qux/b/sub",
                "qux/c",
                "qux/c/sub",
            ],
            '/',
        );

        {
            let mut r: Vec<String> = Vec::default();
            m.all_suffixes_of_into("foo", '.', &mut r);
            assert!(r.is_empty());
        }
        {
            let mut r: Vec<String> = Vec::default();
            m.all_suffixes_of_into("bar", '.', &mut r);
            r.sort();
            assert_eq!(vec!["bar.v1", "bar.v2"], r);
        }
        {
            let mut r: Vec<String> = Vec::default();
            m.all_suffixes_of_into("baz", '.', &mut r);
            assert!(r.is_empty());
        }
        {
            let mut r: Vec<String> = Vec::default();
            m.all_suffixes_of_into("qux", '.', &mut r);
            r.sort();
            assert_eq!(
                vec![
                    "qux.a",
                    "qux.a.sub",
                    "qux.b",
                    "qux.b.sub",
                    "qux.c",
                    "qux.c.sub"
                ],
                r
            );
        }
        {
            let mut r: Vec<String> = Vec::default();
            m.all_suffixes_of_into("qux.a", '.', &mut r);
            r.sort();
            assert_eq!(vec!["qux.a.sub"], r);
        }

        assert_eq!(false, m.matches("", '/'));
        assert_eq!(false, m.matches("f", '/'));
        assert_eq!(false, m.matches("fo", '/'));
        assert_eq!(true, m.matches("foo", '/'));
        assert_eq!(false, m.matches("fool", '/'));
        assert_eq!(false, m.matches("foo.l", '/'));
        assert_eq!(true, m.matches("foo.l", '.'));
        assert_eq!(true, m.matches("foo/l", '/'));
        assert_eq!(false, m.matches("foo/l", '.'));

        assert_eq!(false, m.matches("bar", '/'));
        assert_eq!(true, m.matches("bar/v1", '/'));
        assert_eq!(true, m.matches("bar.v1", '.'));
        assert_eq!(true, m.matches("bar/v1/sub", '/'));
        assert_eq!(true, m.matches("bar.v1.sub", '.'));

        assert_eq!(true, m.matches("bar/v2", '/'));
        assert_eq!(true, m.matches("bar.v2", '.'));
        assert_eq!(false, m.matches("bar.v3", '.'));

        assert_eq!(false, m.matches("qux", '/'));
        assert_eq!(true, m.matches("qux/a", '/'));
        assert_eq!(true, m.matches("qux/b", '/'));
        assert_eq!(true, m.matches("qux/c", '/'));
        assert_eq!(true, m.matches("qux.a", '.'));
        assert_eq!(true, m.matches("qux.b", '.'));
        assert_eq!(true, m.matches("qux.c", '.'));
        assert_eq!(false, m.matches("qux/d", '/'));
        assert_eq!(false, m.matches("qux.d", '.'));
        assert_eq!(true, m.matches("qux/a/sub", '/'));
        assert_eq!(true, m.matches("qux/b/sub", '/'));
        assert_eq!(true, m.matches("qux/c/sub", '/'));
        assert_eq!(true, m.matches("qux/a/sub/1", '/'));
        assert_eq!(true, m.matches("qux/b/sub/1/2", '/'));
        assert_eq!(true, m.matches("qux/c/sub/1/2/3", '/'));

        assert_eq!(false, m.strict_prefix("foo", '.'));
        assert_eq!(true, m.strict_prefix("bar", '.'));
        assert_eq!(false, m.strict_prefix("bar/.v1", '.'));
        assert_eq!(true, m.strict_prefix("qux", '.'));
        assert_eq!(false, m.strict_prefix("qux.a", '.'));
        assert_eq!(false, m.strict_prefix("qux.a.sub", '.'));

        assert_eq!("", m.longest_prefix("", '/'));
        assert_eq!("", m.longest_prefix("f", '/'));
        assert_eq!("", m.longest_prefix("fo", '/'));
        assert_eq!("foo", m.longest_prefix("foo", '/'));
        assert_eq!("", m.longest_prefix("fool", '/'));
        assert_eq!("", m.longest_prefix("foo.l", '/'));
        assert_eq!("foo", m.longest_prefix("foo.l", '.'));
        assert_eq!("foo", m.longest_prefix("foo/l", '/'));
        assert_eq!("", m.longest_prefix("foo/l", '.'));

        assert_eq!("", m.longest_prefix("bar", '/'));
        assert_eq!("bar/v1", m.longest_prefix("bar/v1", '/'));
        assert_eq!("bar.v1", m.longest_prefix("bar.v1", '.'));
        assert_eq!("bar/v1", m.longest_prefix("bar/v1/sub", '/'));
        assert_eq!("bar.v1", m.longest_prefix("bar.v1.sub", '.'));

        assert_eq!("bar/v2", m.longest_prefix("bar/v2", '/'));
        assert_eq!("bar.v2", m.longest_prefix("bar.v2", '.'));

        assert_eq!("", m.longest_prefix("qux", '/'));
        assert_eq!("qux/a", m.longest_prefix("qux/a", '/'));
        assert_eq!("qux/b", m.longest_prefix("qux/b", '/'));
        assert_eq!("qux/c", m.longest_prefix("qux/c", '/'));
        assert_eq!("qux.a", m.longest_prefix("qux.a", '.'));
        assert_eq!("qux.b", m.longest_prefix("qux.b", '.'));
        assert_eq!("qux.c", m.longest_prefix("qux.c", '.'));
        assert_eq!("", m.longest_prefix("qux/d", '/'));
        assert_eq!("", m.longest_prefix("qux.d", '.'));
        assert_eq!("qux/a/sub", m.longest_prefix("qux/a/sub", '/'));
        assert_eq!("qux/b/sub", m.longest_prefix("qux/b/sub", '/'));
        assert_eq!("qux/c/sub", m.longest_prefix("qux/c/sub", '/'));
        assert_eq!("qux/a/sub", m.longest_prefix("qux/a/sub/1", '/'));
        assert_eq!("qux/b/sub", m.longest_prefix("qux/b/sub/1/2", '/'));
        assert_eq!("qux/c/sub", m.longest_prefix("qux/c/sub/1/2/3", '/'));
    }

    #[test]
    fn add() {
        let mut m = MatcherNode::new();
        m.add("foo.bar.baz", '.');
        m.add("foo/baz/bar", '/');
        m.add("foo", '/');
        m.add("bar/baz", '/');
        m.add("foo/baz", '/');

        assert_eq!(2, m.children.len());
        assert_eq!(true, m.matches("foo", '/'));
        assert_eq!(true, m.matches("foo.baz", '.'));
        assert_eq!(true, m.matches("foo/bar", '/'));
        assert_eq!(true, m.matches("foo/bar/baz", '/'));
        assert_eq!(true, m.matches("foo/baz/bar", '/'));
        assert_eq!(true, m.matches("bar.baz", '.'));
        assert_eq!(false, m.matches("fool", '.'));
        assert_eq!(false, m.matches("fool.ed", '.'));
        assert_eq!(false, m.matches("baz", '.'));
        assert_eq!(false, m.matches("baz.bar", '.'));

        assert_eq!(false, m.strict_prefix("foo", '/'));
        assert_eq!(false, m.strict_prefix("foo.baz", '.'));
        assert_eq!(true, m.strict_prefix("foo/bar", '/'));
        assert_eq!(false, m.strict_prefix("foo/bar/baz", '/'));
        assert_eq!(false, m.strict_prefix("foo/baz/bar", '/'));
        assert_eq!(true, m.strict_prefix("bar", '.'));
        assert_eq!(false, m.strict_prefix("bar.baz", '.'));
        assert_eq!(false, m.strict_prefix("fool", '.'));
        assert_eq!(false, m.strict_prefix("fool.ed", '.'));
        assert_eq!(false, m.strict_prefix("baz", '.'));
        assert_eq!(false, m.strict_prefix("baz.bar", '.'));

        assert_eq!("foo", m.longest_prefix("foo", '/'));
        assert_eq!("foo.baz", m.longest_prefix("foo.baz", '.'));
        assert_eq!("foo", m.longest_prefix("foo/bar", '/'));
        assert_eq!("foo/bar/baz", m.longest_prefix("foo/bar/baz", '/'));
        assert_eq!("foo/baz/bar", m.longest_prefix("foo/baz/bar", '/'));
        assert_eq!("bar.baz", m.longest_prefix("bar.baz", '.'));
        assert_eq!("", m.longest_prefix("fool", '.'));
        assert_eq!("", m.longest_prefix("fool.ed", '.'));
        assert_eq!("", m.longest_prefix("baz.bar", '.'));
    }
}
