//! EndPlayDesktop controller for MXU (macOS only).
//! Selected by its own ControllerConfig variant. Input and capture remain in
//! MaaEnd's shared Python device layer; runtime paths come from the project interface.

use maa_framework::common::{ControllerFeature, MaaId};
use maa_framework::controller::Controller;
use maa_framework::custom_controller::CustomControllerCallback;
use maa_framework::event_sink::EventSink;
use maa_framework::notification::MaaEvent;
use serde_json::{json, Value};
use std::io::{Read, Write};
use std::net::Shutdown;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex, Weak};
use std::time::{Duration, Instant};

pub const UUID: &str = "maa.endplaydesktop";
const MAX_HEADER: usize = 64 * 1024;
const MAX_IMAGE: usize = 32 * 1024 * 1024;

struct Manifest {
    python: PathBuf,
    project_dir: PathBuf,
}

struct Connection {
    child: Child,
    wire: UnixStream,
}

impl Connection {
    fn start(manifest: &Manifest, address: &str) -> Result<Self, String> {
        let (wire, child_wire) = UnixStream::pair().map_err(|e| e.to_string())?;
        wire.set_read_timeout(Some(Duration::from_secs(20)))
            .map_err(|e| e.to_string())?;
        wire.set_write_timeout(Some(Duration::from_secs(3)))
            .map_err(|e| e.to_string())?;
        let input: OwnedFd = child_wire.try_clone().map_err(|e| e.to_string())?.into();
        let output: OwnedFd = child_wire.into();
        let child = Command::new(&manifest.python)
            .current_dir(&manifest.project_dir)
            .args([
                "-m",
                "tools.EndPlayDesktop",
                "--maatools-address",
                address,
                "sidecar",
            ])
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .stdin(Stdio::from(input))
            .stdout(Stdio::from(output))
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(Self { child, wire })
    }

    fn rpc(&mut self, op: &str, args: &[i32]) -> Result<(Value, Vec<u8>), String> {
        let body =
            serde_json::to_vec(&json!({ "op": op, "args": args })).map_err(|e| e.to_string())?;
        self.wire
            .write_all(&(body.len() as u32).to_be_bytes())
            .and_then(|_| self.wire.write_all(&body))
            .map_err(|e| e.to_string())?;
        let mut length = [0u8; 4];
        self.wire
            .read_exact(&mut length)
            .map_err(|e| e.to_string())?;
        let size = u32::from_be_bytes(length) as usize;
        if size == 0 || size > MAX_HEADER {
            return Err("invalid controller response length".into());
        }
        let mut body = vec![0; size];
        self.wire.read_exact(&mut body).map_err(|e| e.to_string())?;
        let response: Value = serde_json::from_slice(&body).map_err(|e| e.to_string())?;
        let payload_size = response["payload_size"]
            .as_u64()
            .filter(|size| *size <= MAX_IMAGE as u64)
            .ok_or("invalid screenshot response length")? as usize;
        if op != "screencap" && payload_size != 0 {
            return Err("unexpected controller payload".into());
        }
        let mut payload = vec![0; payload_size];
        self.wire
            .read_exact(&mut payload)
            .map_err(|e| e.to_string())?;
        if response["ok"].as_bool() != Some(true) {
            return Err(response["error"]
                .as_str()
                .unwrap_or("controller operation failed")
                .into());
        }
        Ok((response["result"].clone(), payload))
    }
}

impl Drop for Connection {
    fn drop(&mut self) {
        // EOF makes the sidecar release its session even if MXU is disconnected
        // between tasks. Bound process cleanup; never leave an input daemon.
        let _ = self.wire.shutdown(Shutdown::Both);
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

struct Driver {
    manifest: Manifest,
    address: String,
    connection: Mutex<Option<Connection>>,
}

impl Driver {
    fn request(&self, op: &str, args: &[i32]) -> Result<(Value, Vec<u8>), String> {
        let mut connection = self
            .connection
            .lock()
            .map_err(|_| "controller channel poisoned")?;
        if op == "connect" && connection.is_none() {
            *connection = Some(Connection::start(&self.manifest, &self.address)?);
        }
        let result = connection
            .as_mut()
            .ok_or("controller channel closed")?
            .rpc(op, args);
        if result.is_err() {
            connection.take();
        }
        result
    }
}

// The Rust binding retains CustomController callbacks independently of the
// Controller handle. Keep only a Weak in callbacks; the owned event sink below
// ties process lifetime to the actual controller and its native sinks.
struct Callback(Weak<Driver>);
struct Lifetime(Arc<Driver>);

impl EventSink for Lifetime {
    fn on_event(&self, _handle: MaaId, _event: &MaaEvent) {
        let _ = &self.0;
    }
}

impl Callback {
    fn request(&self, op: &str, args: &[i32]) -> Option<(Value, Vec<u8>)> {
        let driver = self.0.upgrade()?;
        match driver.request(op, args) {
            Ok(value) => Some(value),
            Err(error) => {
                log::error!("EndPlayDesktop {op} failed: {error}");
                None
            }
        }
    }

    fn action(&self, op: &str, args: &[i32]) -> bool {
        self.request(op, args)
            .is_some_and(|(result, _)| result.as_bool() == Some(true))
    }
}

impl CustomControllerCallback for Callback {
    fn connect(&self) -> bool {
        self.action("connect", &[])
    }
    fn connected(&self) -> bool {
        self.action("connected", &[])
    }
    fn request_uuid(&self) -> Option<String> {
        Some(UUID.into())
    }
    fn get_features(&self) -> ControllerFeature {
        ControllerFeature::USE_MOUSE_DOWN_UP_INSTEAD_OF_CLICK
            | ControllerFeature::USE_KEY_DOWN_UP_INSTEAD_OF_CLICK
    }
    fn screencap(&self) -> Option<Vec<u8>> {
        self.request("screencap", &[])
            .and_then(|(result, payload)| {
                (result.as_bool() == Some(true) && !payload.is_empty()).then_some(payload)
            })
    }
    fn touch_down(&self, contact: i32, x: i32, y: i32, pressure: i32) -> bool {
        self.action("touch_down", &[contact, x, y, pressure])
    }
    fn touch_move(&self, contact: i32, x: i32, y: i32, pressure: i32) -> bool {
        self.action("touch_move", &[contact, x, y, pressure])
    }
    fn touch_up(&self, contact: i32) -> bool {
        self.action("touch_up", &[contact])
    }
    fn key_down(&self, keycode: i32) -> bool {
        self.action("key_down", &[keycode])
    }
    fn key_up(&self, keycode: i32) -> bool {
        self.action("key_up", &[keycode])
    }
    fn scroll(&self, dx: i32, dy: i32) -> bool {
        self.action("scroll", &[dx, dy])
    }
    fn relative_move(&self, dx: i32, dy: i32) -> bool {
        self.action("relative_move", &[dx, dy])
    }
    fn inactive(&self) -> bool {
        self.action("inactive", &[])
    }
    fn get_info(&self) -> String {
        json!({ "backend": "EndPlayDesktop", "layout": "desktop", "keycode": "win32_vk" })
            .to_string()
    }
}

pub fn create(
    directory: &Path,
    python: &str,
    project_dir: &str,
    address: &str,
) -> Result<Controller, String> {
    let manifest = Manifest {
        python: directory.join(python),
        project_dir: directory.join(project_dir),
    };
    if !manifest.python.is_absolute()
        || !manifest.python.is_file()
        || !manifest.project_dir.is_absolute()
        || !manifest
            .project_dir
            .join("tools/EndPlayDesktop/sidecar.py")
            .is_file()
    {
        return Err("invalid EndPlayDesktop Python runtime or project directory".into());
    }
    let driver = Arc::new(Driver {
        manifest,
        address: address.into(),
        connection: Mutex::new(None),
    });
    let controller =
        Controller::new_custom(Callback(Arc::downgrade(&driver))).map_err(|e| e.to_string())?;
    controller
        .add_event_sink(Box::new(Lifetime(driver)))
        .map_err(|e| e.to_string())?;
    Ok(controller)
}
