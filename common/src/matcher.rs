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

    pub fn from<'a, T: IntoIterator<Item = &'a String>>(values: T, sep: char) -> MatcherNode {
        let mut tree = Self::new();
        for val in values {
            tree.add(val, sep);
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
