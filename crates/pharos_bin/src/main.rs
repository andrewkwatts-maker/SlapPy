//! pharos-headless: standalone Rust+wgpu runtime, no Python required.
//!
//! Usage:
//!
//! ```text
//! pharos-headless <scene.yaml> [--out frame.png] [--width 1280] [--height 720]
//! ```
//!
//! Loads a `RenderScene` (via serde_yaml), boots the wgpu backend, and
//! writes one PNG frame. Sprint 4 skeleton; Sprint 5 wires glTF mesh
//! loading through the scene loader.

use std::path::{Path, PathBuf};

use pharos_render::{BackendKind, RenderScene, Renderer};

#[derive(Debug)]
struct Args {
    scene: PathBuf,
    out: PathBuf,
    width: u32,
    height: u32,
    backend: BackendKind,
}

fn parse_args() -> Result<Args, String> {
    let mut it = std::env::args().skip(1);
    let mut scene: Option<PathBuf> = None;
    let mut out = PathBuf::from("frame.png");
    let mut width: u32 = 1280;
    let mut height: u32 = 720;
    let mut backend = BackendKind::Wgpu;

    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--out" => {
                out = PathBuf::from(it.next().ok_or("--out requires a path")?);
            }
            "--width" => {
                width = it
                    .next()
                    .ok_or("--width requires a value")?
                    .parse()
                    .map_err(|e: std::num::ParseIntError| e.to_string())?;
            }
            "--height" => {
                height = it
                    .next()
                    .ok_or("--height requires a value")?
                    .parse()
                    .map_err(|e: std::num::ParseIntError| e.to_string())?;
            }
            "--backend" => {
                let name = it.next().ok_or("--backend requires wgpu|cpu")?;
                backend = match name.as_str() {
                    "wgpu" => BackendKind::Wgpu,
                    "cpu" => BackendKind::CpuFallback,
                    other => return Err(format!("unknown backend: {other}")),
                };
            }
            "-h" | "--help" => {
                print_usage();
                std::process::exit(0);
            }
            positional if scene.is_none() => {
                scene = Some(PathBuf::from(positional));
            }
            other => return Err(format!("unexpected argument: {other}")),
        }
    }

    let scene = scene.ok_or_else(|| "missing scene.yaml path".to_string())?;
    Ok(Args { scene, out, width, height, backend })
}

fn print_usage() {
    eprintln!("pharos-headless <scene.yaml> [--out frame.png] [--width N] [--height N] [--backend wgpu|cpu]");
}

fn load_scene(path: &Path) -> Result<RenderScene, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| format!("read scene: {e}"))?;
    // Missing/empty scene files render a clear-colour frame — useful for
    // smoke-testing the wgpu init path without an authored scene.
    if raw.trim().is_empty() {
        return Ok(RenderScene::default());
    }
    serde_yaml::from_str::<SceneFile>(&raw)
        .map(SceneFile::into_scene)
        .map_err(|e| format!("parse scene: {e}"))
}

#[derive(Debug, serde::Deserialize)]
struct SceneFile {
    #[serde(default = "default_clear")]
    clear_colour: [f32; 4],
    #[serde(default)]
    camera: Option<pharos_render::Camera3D>,
}

fn default_clear() -> [f32; 4] {
    [0.05, 0.06, 0.08, 1.0]
}

impl SceneFile {
    fn into_scene(self) -> RenderScene {
        RenderScene {
            camera: self.camera.unwrap_or_default(),
            items: Vec::new(),
            clear_colour: self.clear_colour,
        }
    }
}

fn main() {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("pharos-headless: {e}");
            print_usage();
            std::process::exit(2);
        }
    };

    let scene = match load_scene(&args.scene) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("pharos-headless: {e}");
            std::process::exit(3);
        }
    };

    let mut renderer = match Renderer::new(args.backend, args.width, args.height) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("pharos-headless: renderer init: {e}");
            std::process::exit(4);
        }
    };

    let pixels = match renderer.render_to_rgba(&scene) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("pharos-headless: render_to_rgba: {e}");
            std::process::exit(5);
        }
    };

    let img = image::RgbaImage::from_raw(args.width, args.height, pixels)
        .expect("RgbaImage size mismatch");
    if let Err(e) = img.save(&args.out) {
        eprintln!("pharos-headless: save {}: {e}", args.out.display());
        std::process::exit(6);
    }

    println!(
        "pharos-headless: wrote {} ({}x{}, backend={:?})",
        args.out.display(),
        args.width,
        args.height,
        args.backend
    );
}
