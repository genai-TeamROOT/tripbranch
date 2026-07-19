#!/usr/bin/env node
import { spawn } from "node:child_process";

const isWindows = process.platform === "win32";

const commands = [
  {
    name: "FRONTEND",
    command: "npm",
    args: ["run", "dev", "--prefix", "frontend"],
  },
  {
    name: "BACKEND",
    command: "python",
    args: ["-m", "uvicorn", "app.main:app", "--reload", "--app-dir", "backend", "--port", "8000"],
  },
];

const children = commands.map(({ name, command, args }) => {
  const child = spawn(command, args, {
    stdio: "inherit",
    shell: isWindows,
  });

  child.on("exit", (code) => {
    if (shuttingDown) return;
    console.error(`${name} exited with code ${code ?? 1}`);
    shutdown(code ?? 1);
  });

  child.on("error", (error) => {
    console.error(`${name} failed to start: ${error.message}`);
    shutdown(1);
  });

  return child;
});

let shuttingDown = false;

function shutdown(code) {
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill();
  }
  process.exit(code);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
