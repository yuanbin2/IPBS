import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const backendRoot = resolve(frontendRoot, "../backend");
const repositoryRoot = resolve(backendRoot, "..");
const python = process.env.E2E_PYTHON || (process.platform === "win32"
  ? resolve(repositoryRoot, ".venv/Scripts/python.exe")
  : resolve(repositoryRoot, ".venv/bin/python"));
const password = "Upload-e2e-only-2026!";

function setup(args, env) {
  const result = spawnSync(python, args, { cwd: backendRoot, env, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`E2E setup command failed (${args.join(" ")}).`);
}

function reserveEphemeralPort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (!address || typeof address === "string") return reject(new Error("Unable to reserve a local API port."));
      const port = address.port;
      server.close((error) => (error ? reject(error) : resolvePort(port)));
    });
  });
}

function assertFrontendPortAvailable(port) {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", () => reject(new Error(`E2E frontend port ${port} is already in use; set E2E_FRONTEND_PORT to an unused port.`)));
    server.listen(Number(port), "127.0.0.1", () => {
      server.close((error) => (error ? reject(error) : resolvePort()));
    });
  });
}

async function waitForBackend(port) {
  const url = `http://127.0.0.1:${port}/api/agent/auth/login/`;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.status < 500) return;
    } catch {
      // Django is still starting; retry within the bounded startup window.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 200));
  }
  throw new Error("Django upload E2E server did not become ready within 20 seconds.");
}

export async function startServices() {
  const temporaryRoot = mkdtempSync(resolve(tmpdir(), "blog-upload-e2e-"));
  const frontendPort = process.env.E2E_FRONTEND_PORT || "5173";
  const baseEnv = {
    ...process.env,
    DJANGO_SETTINGS_MODULE: "config.settings_e2e",
    E2E_DATA_ROOT: temporaryRoot,
    BLOG_LOCAL_MODE: "true",
    BLOG_MEDIA_STORAGE: "file",
    AGENT_SECURITY_ENFORCED: "true",
    CELERY_TASK_ALWAYS_EAGER: "true",
    CELERY_TASK_EAGER_PROPAGATES: "true",
    DJANGO_SECRET_KEY: "isolated-upload-e2e-secret-key-2026",
    OPENAI_API_KEY: "",
    OPENAI_EMBEDDING_API_KEY: "",
    BAILIAN_API_KEY: "",
    DASHSCOPE_API_KEY: "",
    LANGSMITH_TRACING: "false",
    LANGCHAIN_TRACING_V2: "false",
  };
  const children = [];
  let stopping = false;

  async function stop() {
    if (stopping) return;
    stopping = true;
    console.log("Stopping isolated upload E2E services.");
    for (const child of children) {
      if (process.platform === "win32" && child.pid) {
        spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      } else {
        child.kill("SIGTERM");
      }
    }
    await Promise.all(children.map((child) => new Promise((resolveClose) => {
      if (child.exitCode !== null) return resolveClose();
      const timeout = setTimeout(resolveClose, 5_000);
      child.once("exit", () => {
        clearTimeout(timeout);
        resolveClose();
      });
    })));

    const expectedParent = resolve(tmpdir());
    if (dirname(temporaryRoot) === expectedParent && basename(temporaryRoot).startsWith("blog-upload-e2e-")) {
      rmSync(temporaryRoot, { recursive: true, force: true });
    }
    console.log("Isolated upload E2E services stopped and temporary data removed.");
  }

  try {
    await assertFrontendPortAvailable(frontendPort);
    setup(["manage.py", "migrate", "--noinput"], baseEnv);
    setup(["manage.py", "create_upload_e2e_user", "--password", password, "--workspace", "e2e-writer-a"], baseEnv);
    setup(["manage.py", "create_upload_e2e_user", "--password", password, "--username", "upload-e2e-other", "--workspace", "e2e-writer-b"], baseEnv);
    setup(["manage.py", "create_upload_e2e_user", "--password", password, "--username", "upload-e2e-admin", "--workspace", "e2e-writer-a", "--role", "admin"], baseEnv);
    setup(["manage.py", "create_upload_e2e_user", "--password", password, "--username", "upload-e2e-reader", "--workspace", "e2e-writer-a", "--role", "visitor"], baseEnv);

    const backendPort = await reserveEphemeralPort();
    console.log(`Using isolated Django test service on 127.0.0.1:${backendPort}.`);
    const backend = spawn(python, ["manage.py", "runserver", `127.0.0.1:${backendPort}`, "--noreload"], {
      cwd: backendRoot,
      env: baseEnv,
      stdio: ["ignore", "pipe", "pipe"],
    });
    backend.stdout?.on("data", (chunk) => process.stdout.write(chunk));
    backend.stderr?.on("data", (chunk) => process.stderr.write(chunk));
    children.push(backend);
    await waitForBackend(backendPort);

    const vite = spawn(process.execPath, [resolve(frontendRoot, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", frontendPort, "--strictPort"], {
      cwd: frontendRoot,
      env: { ...baseEnv, VITE_API_PROXY_TARGET: `http://127.0.0.1:${backendPort}`, VITE_PORT: frontendPort },
      stdio: ["ignore", "pipe", "pipe"],
    });
    vite.stdout?.on("data", (chunk) => process.stdout.write(chunk));
    vite.stderr?.on("data", (chunk) => process.stderr.write(chunk));
    children.push(vite);
    for (const child of children) {
      child.once("error", (error) => console.error("Upload E2E service failed:", error));
    }
    return stop;
  } catch (error) {
    await stop();
    throw error;
  }
}
