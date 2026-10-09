// Live reload of exported data in dev.
//
// The Python exporter writes public/data/status.json last; when it changes, this plugin
// sends its content to the page as the HMR event "metro:data". The viewer then refetches
// only the files listed in `changed` and keeps the camera and the selection.
//
// In `vite --mode model` (npm run model) it also starts the Python watcher, so one command
// gives the whole modelling loop. `--mode model-sample` watches data/sample/campus.

import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Plugin, ViteDevServer } from "vite";

const EVENT = "metro:data";

function startWatcher(server: ViteDevServer, sample: boolean): ChildProcess {
  const repo = resolve(server.config.root, "..");
  const args = ["run", "scripts/06_export_web.py", "--campus", "--watch", ...(sample ? ["--sample"] : [])];
  const child = spawn("uv", args, { cwd: repo, stdio: "inherit", shell: process.platform === "win32" });
  child.on("exit", (code) => {
    if (code) server.config.logger.error(`[metro-data] the Python watcher exited with code ${code}`);
  });
  return child;
}

export function metroData(): Plugin {
  let watcher: ChildProcess | null = null;
  return {
    name: "metro-data",
    apply: "serve",
    configureServer(server) {
      const status = resolve(server.config.publicDir, "data", "status.json");
      server.watcher.add(status);
      let last = "";
      const onChange = (file: string) => {
        if (resolve(file) !== status) return;
        let text: string;
        try {
          text = readFileSync(status, "utf8");
          JSON.parse(text); // half-written file: wait for the next change event
        } catch {
          return;
        }
        if (text === last) return;
        last = text;
        server.ws.send({ type: "custom", event: EVENT, data: JSON.parse(text) });
      };
      server.watcher.on("change", onChange);
      server.watcher.on("add", onChange);

      const mode = server.config.mode;
      if (mode === "model" || mode === "model-sample") {
        watcher = startWatcher(server, mode === "model-sample");
        const stop = () => {
          if (!watcher || watcher.exitCode !== null || watcher.pid === undefined) return;
          // on Windows the watcher runs under a shell: end the whole process tree
          if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(watcher.pid), "/T", "/F"]);
          else watcher.kill();
          watcher = null;
        };
        server.httpServer?.on("close", stop);
        process.on("exit", stop);
      }
    },
  };
}
