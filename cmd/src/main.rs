use std::env;
use std::collections::{HashMap, HashSet};
use std::fs::read_to_string;
use std::process::exit;
use std::time::Instant;
use common::graph::*;
use common::transitive_closure::TransitiveClosure;

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() < 2 {
        exit(1);
    }

    let mut g: Option<TransitiveClosure> = None;

    for mut i in 1..args.len() {
        let start = Instant::now();
        if &args[i] == "--parse" && i+1 < args.len() {
            i += 1;
            let mut packages: HashMap<String, String> = HashMap::new();

            if args[i].starts_with('@') {
                for line in read_to_string(&args[i][1..]).unwrap().split('\n') {
                    let (py_path, fs_path) = line.split_once(':').unwrap();
                    packages.insert(py_path.to_string(), fs_path.to_string());
                }
            } else {
                packages.extend(
                    args[i].split(',').map(
                        |s| {
                            let (a, b) = s.rsplit_once(':').unwrap();
                            (a.to_string(), b.to_string())
                        }
                    )
                )
            }

            eprintln!("building module graph for {} packages", packages.len());

            let module_graph = ModuleGraph::new(
                packages,
                HashSet::from_iter(["affirm".to_string()]),
                HashSet::from_iter(["tests".to_string()]),
                HashSet::new(),
            );

            module_graph.parse_parallel().expect("failed to parse module graph");

            eprintln!("built: {}",
                      Instant::now().duration_since(start).as_millis());

            let tc = module_graph.finalize();

            eprintln!("finalized {}",
                      Instant::now().duration_since(start).as_millis());
            g.replace(tc);
        } else if &args[i] == "--dump" && i+1 < args.len() {
            i += 1;
            if let Some(mg) = g.as_ref() {
                mg.to_small_text_file(&args[i])
                    .expect("failed to dump module graph");
            }
            eprintln!("written out {}",
                      Instant::now().duration_since(start).as_millis());
        }  else if &args[i] == "--save" && i+1 < args.len() {
            i += 1;
            if let Some(mg) = g.as_ref() {
                mg.to_file(&args[i])
                    .expect("failed to serialize module graph");
            }
            eprintln!("written out {}",
                      Instant::now().duration_since(start).as_millis());
        } else if &args[i] == "--load" && i+1 < args.len() {
            i += 1;
            g.replace(TransitiveClosure::from_file(&args[i])
                .expect("failed to deserialize module graph"));
            eprintln!("reloaded {}",
                      Instant::now().duration_since(start).as_millis());
        } else if &args[i] == "--affected" {
            i += 1;
            let affected = g.as_ref().unwrap().affected_by(&args[i..i+1]);
            eprintln!("affected by {}:", &args[i]);
            for (pkg, files) in &affected {
                eprintln!("  - {}:", pkg);
                for f in files {
                    eprintln!("      - {}", f);
                }
            }
        } else if &args[i] == "--affected" {
            i += 1;
            let deps = g.as_ref().unwrap().module_depends_on(&args[i], None);
            eprintln!("depends on {}: {:?}", &args[i], deps);
        }
    }

    exit(0);
}
