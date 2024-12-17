use common::matcher::MatcherNode;

use divan::{bench, Bencher};
use rand::{thread_rng, RngCore};

fn main() {
    divan::main();
}

fn gen_values(count: usize, depth: usize, branch: usize, sep: char) -> Vec<String> {
    let mut values = Vec::with_capacity(count);
    for n in 0..count {
        let mut v = String::with_capacity(6 * depth + 32);
        for d in 0..depth - 1 {
            v.push('d');
            v.push_str(&format!("{}", d));
            v.push('b');
            v.push_str(&format!(
                "{}",
                rand::thread_rng().next_u64() as usize % branch
            ));
            v.push(sep)
        }
        v.push_str(format!("v{}", n).as_str());
        values.push(v);
    }
    values
}

const MATRIX: &[(usize, usize, usize)] = &[
    (10, 1, 1),
    (100, 1, 1),
    (1000, 1, 1),
    (10, 2, 2),
    (100, 2, 2),
    (1000, 2, 2),
    (100, 2, 4),
    (1000, 2, 4),
    (100, 2, 8),
    (1000, 2, 8),
    (10, 4, 2),
    (100, 4, 2),
    (1000, 4, 2),
    (100, 4, 4),
    (1000, 4, 4),
    (100, 4, 8),
    (1000, 4, 8),
    (10, 8, 2),
    (100, 8, 2),
    (1000, 8, 2),
    (100, 8, 4),
    (1000, 8, 4),
    (100, 8, 8),
    (1000, 8, 8),
];

#[bench]
fn default() {
    MatcherNode::default();
}

#[bench(args = MATRIX)]
fn from(bencher: Bencher, params: (usize, usize, usize)) {
    let (count, depth, branch) = params;
    let values = gen_values(count, depth, branch, '.');
    bencher.bench(|| MatcherNode::from(values.clone(), '.'))
}

#[bench(args = MATRIX)]
fn from_iter(bencher: Bencher, params: (usize, usize, usize)) {
    let (count, depth, branch) = params;
    let values = gen_values(count, depth, branch, '.');
    bencher.bench(|| MatcherNode::from(values.iter(), '.'))
}

#[bench(args=MATRIX)]
fn matches(bencher: Bencher, params: (usize, usize, usize)) {
    let (count, depth, branch) = params;
    let values = gen_values(count, depth, branch, '.');
    let m = MatcherNode::from_iter(values.iter(), '.');

    bencher.bench(|| {
        let idx = thread_rng().next_u64() % count as u64;
        let val = values.get(idx as usize).unwrap();
        m.matches(&val, '.');
    });
}

#[bench(args=MATRIX)]
fn strict_prefix(bencher: Bencher, params: (usize, usize, usize)) {
    let (count, depth, branch) = params;
    let values = gen_values(count, depth, branch, '.');
    let m = MatcherNode::from_iter(values.iter(), '.');

    bencher.bench(|| {
        let idx = thread_rng().next_u64() % count as u64;
        let val = values.get(idx as usize).unwrap();
        m.strict_prefix(&val, '.');
    });
}

#[bench(args=MATRIX)]
fn longest_prefix(bencher: Bencher, params: (usize, usize, usize)) {
    let (count, depth, branch) = params;
    let values = gen_values(count, depth, branch, '.');
    let m = MatcherNode::from_iter(values.iter(), '.');

    bencher.bench(|| {
        let idx = thread_rng().next_u64() % count as u64;
        let val = values.get(idx as usize).unwrap();
        m.longest_prefix(&val, '.');
    });
}
