use std::{env, fs, path::PathBuf, process::Command};

fn main() {
    let root = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=scripts/pack_plugin.py");
    println!("cargo:rerun-if-changed=python/plugin_tools.py");
    let mut generated = String::from("pub const PACKAGES: &[(&str, &[u8])] = &[\n");
    for id in ["desk-note", "local-gallery", "codex-companion"] {
        println!("cargo:rerun-if-changed=plugins/{id}");
        if env::var("PROFILE").as_deref() != Ok("release") {
            continue;
        }
        let archive = out.join(format!("{id}.screen-plugin.zip"));
        let result = Command::new("python")
            .arg(root.join("scripts/pack_plugin.py"))
            .arg(root.join("plugins").join(id))
            .arg(&archive)
            .output()
            .expect("Release 内置插件打包需要可用的 python 命令");
        assert!(
            result.status.success(),
            "内置插件 {id} 打包失败：{}",
            String::from_utf8_lossy(&result.stderr)
        );
        generated.push_str(&format!(
            "({id:?}, include_bytes!({:?})),\n",
            archive.to_str().unwrap()
        ));
    }
    generated.push_str("];\n");
    fs::write(out.join("builtin_packages.rs"), generated).unwrap();
    if env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        println!("cargo:rerun-if-changed=packaging/windows/InkHub.ico");
        let version = env::var("CARGO_PKG_VERSION").unwrap();
        let mut parts: Vec<_> = version
            .split('.')
            .map(|p| p.parse::<u16>().unwrap_or(0).to_string())
            .collect();
        parts.resize(4, "0".into());
        let numeric = parts.join(",");
        let rc = out.join("InkHub.rc");
        let res = out.join("InkHub.res");
        let content=format!("#pragma code_page(65001)\n1 ICON {:?}\n1 VERSIONINFO\nFILEVERSION {numeric}\nPRODUCTVERSION {numeric}\nFILEOS 0x40004\nFILETYPE 0x1\nBEGIN\nBLOCK \"StringFileInfo\" BEGIN\nBLOCK \"040904B0\" BEGIN\nVALUE \"FileDescription\", \"墨枢 InkHub\\0\"\nVALUE \"ProductName\", \"InkHub\\0\"\nVALUE \"FileVersion\", \"{version}\\0\"\nVALUE \"ProductVersion\", \"{version}\\0\"\nEND\nEND\nBLOCK \"VarFileInfo\" BEGIN\nVALUE \"Translation\", 0x0409,1200\nEND\nEND\n",root.join("packaging/windows/InkHub.ico").to_str().unwrap());
        fs::write(&rc, content).unwrap();
        let result = Command::new("rc.exe")
            .arg("/nologo")
            .arg(format!("/fo{}", res.display()))
            .arg(&rc)
            .output()
            .expect("Windows 构建需要 Windows SDK 的 rc.exe");
        assert!(
            result.status.success(),
            "资源编译失败：{} {}",
            String::from_utf8_lossy(&result.stdout),
            String::from_utf8_lossy(&result.stderr)
        );
        println!(
            "cargo:rustc-link-arg-bin=note4-screen-scheduler={}",
            res.display()
        );
    }
}
