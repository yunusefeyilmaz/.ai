//! One place to run a shell command with a hard time limit.
//!
//! Used by the project checks (`ai check`, `ai git finish`) and by the
//! blueprint's toolchain probes, so both get the same timeout semantics:
//! stdout/stderr are drained on background threads (a chatty child cannot
//! deadlock on a full pipe), the child is polled, and a process that outlives
//! its budget is killed **with its children** (a shell kid holding the pipe open
//! would otherwise stall the collector) and reported as `timed_out` with exit
//! code 124.

use std::io::Read;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Clone, Debug)]
pub struct Outcome {
    pub code: i32,
    pub stdout: String,
    pub stderr: String,
    pub timed_out: bool,
}

impl Outcome {
    /// stdout and stderr in the order a human reads them.
    pub fn combined(&self) -> String {
        if self.stderr.is_empty() {
            self.stdout.clone()
        } else if self.stdout.is_empty() {
            self.stderr.clone()
        } else {
            format!("{}\n{}", self.stdout, self.stderr)
        }
    }
}

fn shell(command: &str) -> Command {
    #[cfg(windows)]
    {
        let mut child = Command::new("cmd");
        child.arg("/C").arg(command);
        child
    }
    #[cfg(not(windows))]
    {
        let mut child = Command::new("sh");
        child.arg("-c").arg(command);
        // Give the shell its own process group so a timeout can kill the whole
        // tree in one signal instead of leaving grandchildren on our pipes.
        use std::os::unix::process::CommandExt;
        child.process_group(0);
        child
    }
}

fn capture<R: Read + Send + 'static>(mut reader: R) -> Receiver<String> {
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = reader.read_to_end(&mut bytes);
        let _ = sender.send(String::from_utf8_lossy(&bytes).trim_end().to_string());
    });
    receiver
}

/// Kill and reap the child and everything it started.
fn terminate(child: &mut Child) {
    let pid = child.id();
    #[cfg(windows)]
    {
        let _ = Command::new("taskkill")
            .args(["/F", "/T", "/PID", &pid.to_string()])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    #[cfg(not(windows))]
    {
        // `process_group(0)` made the child a group leader: -pid is the tree.
        let _ = Command::new("kill")
            .args(["-9", &format!("-{pid}")])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn collect(receiver: Receiver<String>, wait: Duration) -> String {
    receiver.recv_timeout(wait).unwrap_or_default()
}

/// Run `command` in `cwd`; `None` means no limit (interactive/CI callers).
pub fn run(command: &str, cwd: &Path, timeout: Option<Duration>) -> Outcome {
    let mut child = match shell(command)
        .current_dir(cwd)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(error) => {
            return Outcome {
                code: 127,
                stdout: String::new(),
                stderr: error.to_string(),
                timed_out: false,
            }
        }
    };
    let stdout = child.stdout.take().map(capture);
    let stderr = child.stderr.take().map(capture);
    let deadline = timeout.map(|limit| Instant::now() + limit);
    let mut timed_out = false;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) => {
                if deadline
                    .map(|deadline| Instant::now() >= deadline)
                    .unwrap_or(false)
                {
                    timed_out = true;
                    terminate(&mut child);
                    break None;
                }
                thread::sleep(Duration::from_millis(20));
            }
            Err(error) => {
                return Outcome {
                    code: 127,
                    stdout: stdout
                        .map(|receiver| collect(receiver, Duration::from_millis(500)))
                        .unwrap_or_default(),
                    stderr: error.to_string(),
                    timed_out: false,
                }
            }
        }
    };
    // A killed tree releases its pipes quickly; a finished child has already
    // written everything it is going to write.
    let wait = if timed_out {
        Duration::from_millis(500)
    } else {
        Duration::from_secs(5)
    };
    let stdout = stdout
        .map(|receiver| collect(receiver, wait))
        .unwrap_or_default();
    let stderr = stderr
        .map(|receiver| collect(receiver, wait))
        .unwrap_or_default();
    let code = if timed_out {
        124
    } else {
        status.and_then(|status| status.code()).unwrap_or(124)
    };
    Outcome {
        code,
        stdout,
        stderr,
        timed_out,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn captures_output_and_exit_code() {
        let outcome = run("echo hello", Path::new("."), None);
        assert_eq!(outcome.code, 0);
        assert!(outcome.combined().contains("hello"), "{outcome:?}");
        assert!(!outcome.timed_out);
    }

    #[test]
    fn a_slow_command_is_killed() {
        #[cfg(windows)]
        let command = "ping -n 6 127.0.0.1 >nul";
        #[cfg(not(windows))]
        let command = "sleep 5";
        let started = Instant::now();
        let outcome = run(command, Path::new("."), Some(Duration::from_millis(300)));
        assert!(outcome.timed_out, "{outcome:?}");
        assert_eq!(outcome.code, 124);
        assert!(
            started.elapsed() < Duration::from_secs(4),
            "it must not wait for the child"
        );
    }

    #[test]
    fn a_failing_command_reports_its_code() {
        #[cfg(windows)]
        let outcome = run("exit /B 3", Path::new("."), None);
        #[cfg(not(windows))]
        let outcome = run("exit 3", Path::new("."), None);
        assert_eq!(outcome.code, 3, "{outcome:?}");
    }
}
