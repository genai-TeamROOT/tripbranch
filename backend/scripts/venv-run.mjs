#!/usr/bin/env node
// Runs a command (pytest/ruff/uvicorn/...) using backend/.venv. Deliberately
// simple: if backend/.venv doesn't exist (or looks broken), this fails with
// clear setup instructions instead of silently falling back to some other
// Python on PATH -- a wrong-environment run that "succeeds" is worse than a
// loud failure that tells you what to do.
//
// Usage: node scripts/venv-run.mjs <command> [...args]
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const backendDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const isWindows = process.platform === "win32";
const venvDir = path.join(backendDir, ".venv");
const venvBinDir = path.join(venvDir, isWindows ? "Scripts" : "bin");
const venvMarker = path.join(venvDir, "pyvenv.cfg");

const [cmd, ...args] = process.argv.slice(2);
if (!cmd) {
  console.error("Usage: node scripts/venv-run.mjs <command> [...args]");
  process.exit(1);
}

const candidate = path.join(venvBinDir, isWindows ? `${cmd}.exe` : cmd);
const setupHint =
  "cd backend\n" +
  "  python3 -m venv .venv\n" +
  (isWindows ? "  .venv\\Scripts\\Activate.ps1\n" : "  source .venv/bin/activate\n") +
  "  python -m pip install --upgrade pip\n" +
  '  python -m pip install -e ".[dev]"';

if (!existsSync(venvDir)) {
  console.error(
    `[venv-run] backend/.venv not found. Create it first:\n\n  ${setupHint}\n`,
  );
  process.exit(1);
}
if (!existsSync(venvMarker)) {
  console.error(
    `[venv-run] backend/.venv exists but is missing pyvenv.cfg -- it does not look like a ` +
      `valid virtualenv. Delete it and recreate it:\n\n  rm -rf backend/.venv\n  ${setupHint}\n`,
  );
  process.exit(1);
}
if (!existsSync(candidate)) {
  console.error(
    `[venv-run] backend/.venv exists but has no "${cmd}" executable. Install dependencies:\n\n` +
      `  cd backend\n  .venv/bin/pip install -e ".[dev]"\n`,
  );
  process.exit(1);
}

const resolved = candidate;
console.log(`[venv-run] using: ${resolved}`);
console.log(`[venv-run] running: ${resolved} ${args.join(" ")}`);

const child = spawn(resolved, args, {
  stdio: "inherit",
  shell: isWindows,
  cwd: backendDir,
});

child.on("error", (err) => {
  console.error(`[venv-run] failed to start "${resolved}": ${err.message}`);
  process.exit(1);
});

// Forward termination signals so `npm run dev` (via concurrently -k) or a
// manual Ctrl-C actually stops this child instead of leaving it orphaned.
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    child.kill(signal);
  });
}

child.on("exit", (code, signal) => {
  if (signal) {
    // Killed by a signal (e.g. Ctrl-C): exit 0, this is not a failure.
    process.exit(0);
  }
  process.exit(code ?? 1);
});
